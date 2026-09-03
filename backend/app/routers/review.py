import csv
import io
import re
import uuid
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..deps import get_owned_class, get_owned_student
from ..models import Class, Observation, Student, User
from ..schemas import (
    ClassStats,
    ObservationOut,
    ObservationUpdate,
    SentimentCounts,
    StudentStats,
    StudentSummary,
)

router = APIRouter(prefix="/api", tags=["review"])


def _get_owned_observation(
    observation_id: uuid.UUID, user: User, db: Session
) -> Observation:
    obs = db.get(Observation, observation_id)
    if obs is not None:
        cls = db.get(Class, obs.class_id)
        if cls is not None and cls.user_id == user.id:
            return obs
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Beobachtung nicht gefunden.")


# ---- per-student views ----
@router.get("/students/{student_id}/observations", response_model=list[ObservationOut])
def student_observations(
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    limit: int = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> list[Observation]:
    page = min(limit or settings.default_page_size, settings.max_page_size)
    q = (
        select(Observation)
        .where(Observation.student_id == student.id)
        .order_by(Observation.lesson_date.desc(), Observation.created_at.desc())
        .offset(offset)
        .limit(page)
    )
    return list(db.scalars(q))


@router.get("/students/{student_id}/summary", response_model=StudentSummary)
def student_summary(
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    timeline_limit: int = Query(default=None),
) -> StudentSummary:
    # Aggregate over the whole history in the database rather than pulling every
    # row into Python just to count it.
    rows = db.execute(
        select(Observation.sentiment, func.count())
        .where(Observation.student_id == student.id)
        .group_by(Observation.sentiment)
    ).all()
    counts = SentimentCounts()
    for sentiment, n in rows:
        setattr(counts, sentiment.value, n)
    total = counts.positive + counts.neutral + counts.negative

    avg = db.scalar(
        select(func.avg(Observation.manual_score)).where(
            Observation.student_id == student.id,
            Observation.manual_score.is_not(None),
        )
    )

    # The UI renders a bounded, newest-first list; don't ship a whole school year.
    page = min(timeline_limit or settings.default_page_size, settings.max_page_size)
    timeline = list(
        db.scalars(
            select(Observation)
            .where(Observation.student_id == student.id)
            .order_by(Observation.lesson_date.asc(), Observation.created_at.asc())
            .limit(page + 1)
        )
    )
    truncated = len(timeline) > page
    timeline = timeline[:page]

    return StudentSummary(
        student_id=student.id,
        full_name=student.full_name,
        count=total,
        counts=counts,
        avg_score=round(float(avg), 2) if avg is not None else None,
        timeline=[ObservationOut.model_validate(o) for o in timeline],
        timeline_truncated=truncated,
    )


# ---- class aggregate (overview screen) ----
@router.get("/classes/{class_id}/stats", response_model=ClassStats)
def class_stats(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
) -> ClassStats:
    """Per-pupil sentiment tallies without shipping the observation bodies."""
    rows = db.execute(
        select(
            Observation.student_id,
            Observation.sentiment,
            func.count().label("n"),
        )
        .where(Observation.class_id == cls.id)
        .group_by(Observation.student_id, Observation.sentiment)
    ).all()

    avg_rows = db.execute(
        select(Observation.student_id, func.avg(Observation.manual_score))
        .where(
            Observation.class_id == cls.id,
            Observation.manual_score.is_not(None),
        )
        .group_by(Observation.student_id)
    ).all()
    averages = {sid: avg for sid, avg in avg_rows}

    per_student: dict[uuid.UUID, SentimentCounts] = {}
    unassigned = 0
    for student_id, sentiment, n in rows:
        if student_id is None:
            unassigned += n
            continue
        counts = per_student.setdefault(student_id, SentimentCounts())
        setattr(counts, sentiment.value, n)

    stats = []
    for student_id, counts in per_student.items():
        avg = averages.get(student_id)
        stats.append(
            StudentStats(
                student_id=student_id,
                counts=counts,
                total=counts.positive + counts.neutral + counts.negative,
                avg_score=round(float(avg), 2) if avg is not None else None,
            )
        )

    return ClassStats(students=stats, unassigned=unassigned)


# ---- edit / delete an observation ----
@router.patch("/observations/{observation_id}", response_model=ObservationOut)
def update_observation(
    observation_id: uuid.UUID,
    body: ObservationUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Observation:
    obs = _get_owned_observation(observation_id, user, db)
    patch = body.model_dump(exclude_unset=True)

    if "student_id" in patch and patch["student_id"] is not None:
        student = db.get(Student, patch["student_id"])
        if student is None or student.class_id != obs.class_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Diese Schüler/in gehört nicht zu dieser Klasse.",
            )

    for field, value in patch.items():
        setattr(obs, field, value)
    db.commit()
    db.refresh(obs)
    audit(
        "observation.updated",
        actor=user.id,
        observation_id=obs.id,
        class_id=obs.class_id,
        fields=sorted(patch.keys()),
    )
    return obs


@router.delete("/observations/{observation_id}", status_code=204)
def delete_observation(
    observation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    obs = _get_owned_observation(observation_id, user, db)
    class_id = obs.class_id
    db.delete(obs)
    db.commit()
    audit(
        "observation.deleted",
        actor=user.id,
        observation_id=observation_id,
        class_id=class_id,
    )
    return Response(status_code=204)


# ---- export helpers ----
# Values starting with any of these are executed as formulas by Excel /
# LibreOffice when the CSV is opened.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    """Neutralize spreadsheet formula injection in a cell value."""
    if value is None:
        return ""
    s = str(value)
    if s.startswith(_FORMULA_TRIGGERS):
        return "'" + s
    return s


def _content_disposition(name: str, ext: str) -> str:
    """RFC 6266 attachment header.

    Header values are latin-1, so a name containing e.g. 'ł' or 'ș' cannot go in
    `filename=` directly (it raises on encode). Sanitize for the ASCII fallback
    and use the RFC 5987 `filename*` form to carry the real name.
    """
    stem = re.sub(r"[^\w.-]", "_", name, flags=re.UNICODE).strip("._") or "export"
    stem = stem[:80]
    ascii_fallback = stem.encode("ascii", "replace").decode("ascii")
    return (
        f'attachment; filename="{ascii_fallback}.{ext}"; '
        f"filename*=UTF-8''{quote(f'{stem}.{ext}')}"
    )


# ---- CSV export ----
def _csv_response(rows: list[dict], display_name: str) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel renders umlauts correctly
    writer = csv.DictWriter(
        buf,
        fieldnames=["lesson_date", "student", "sentiment", "manual_score", "text"],
        delimiter=";",  # German Excel default
    )
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(display_name, "csv")},
    )


def _rows_for(observations: list[Observation], name_by_id: dict) -> list[dict]:
    return [
        {
            "lesson_date": o.lesson_date.isoformat(),
            "student": _csv_safe(name_by_id.get(o.student_id, "(ohne Zuordnung)")),
            "sentiment": o.sentiment.value,
            "manual_score": "" if o.manual_score is None else o.manual_score,
            "text": _csv_safe(o.text),
        }
        for o in observations
    ]


@router.get("/classes/{class_id}/export.csv")
def export_class_csv(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    obs = list(
        db.scalars(
            select(Observation)
            .where(Observation.class_id == cls.id)
            .order_by(Observation.lesson_date.asc())
        )
    )
    students = list(
        db.scalars(select(Student).where(Student.class_id == cls.id))
    )
    name_by_id = {s.id: s.full_name for s in students}
    audit("export.csv", actor=user.id, class_id=cls.id, rows=len(obs))
    return _csv_response(_rows_for(obs, name_by_id), cls.name)


@router.get("/students/{student_id}/export.csv")
def export_student_csv(
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    obs = list(
        db.scalars(
            select(Observation)
            .where(Observation.student_id == student.id)
            .order_by(Observation.lesson_date.asc())
        )
    )
    name_by_id = {student.id: student.full_name}
    audit(
        "export.csv",
        actor=user.id,
        student_id=student.id,
        class_id=student.class_id,
        rows=len(obs),
    )
    return _csv_response(_rows_for(obs, name_by_id), student.full_name)


# ---- PDF export (marking-day sheet) ----
_SENTIMENT_LABEL = {
    "positive": ("positiv", "#2e7d4f"),
    "neutral": ("neutral", "#6b7a88"),
    "negative": ("negativ", "#c0392b"),
}


def _fmt_score(score) -> str:
    return "" if score is None else f"{score:g}"


def _summarize(observations: list[Observation]) -> tuple[dict, float | None]:
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    scores = []
    for o in observations:
        counts[o.sentiment.value] += 1
        if o.manual_score is not None:
            scores.append(o.manual_score)
    avg = round(sum(scores) / len(scores), 2) if scores else None
    return counts, avg


def _pdf_response(story, display_name: str) -> Response:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=display_name,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    doc.build(story)
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(display_name, "pdf")},
    )


def _student_flowables(styles, name: str, observations: list[Observation]) -> list:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    counts, avg = _summarize(observations)
    # ReportLab parses Paragraph text as its own markup: an unescaped '<' or a
    # bare '&' raises a parser error. Everything user-supplied must be escaped;
    # markup we generate ourselves (the <font> tag below) must not be.
    flow = [Paragraph(xml_escape(name), styles["Heading2"])]
    summary = (
        f"{len(observations)} Beobachtungen · "
        f"positiv {counts['positive']} · neutral {counts['neutral']} · "
        f"negativ {counts['negative']} · "
        f"Ø Note: {avg if avg is not None else '—'}"
    )
    flow.append(Paragraph(summary, styles["Meta"]))
    flow.append(Spacer(1, 6))

    if not observations:
        flow.append(Paragraph("Keine Beobachtungen.", styles["Cell"]))
        flow.append(Spacer(1, 12))
        return flow

    header = ["Datum", "Stimmung", "Note", "Beobachtung"]
    rows = [header]
    for o in sorted(observations, key=lambda x: x.lesson_date):
        label, color = _SENTIMENT_LABEL[o.sentiment.value]
        d = o.lesson_date
        rows.append(
            [
                Paragraph(f"{d.day:02d}.{d.month:02d}.{d.year}", styles["Cell"]),
                Paragraph(f'<font color="{color}">{label}</font>', styles["Cell"]),
                Paragraph(_fmt_score(o.manual_score), styles["Cell"]),
                Paragraph(xml_escape(o.text), styles["Cell"]),
            ]
        )
    table = Table(rows, colWidths=[62, 62, 34, 365], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5f7c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dce3ea")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 12))
    return flow


def _pdf_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Cell", fontName="Helvetica", fontSize=9, leading=11))
    styles.add(
        ParagraphStyle(
            "Meta",
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#6b7a88"),
        )
    )
    return styles


@router.get("/students/{student_id}/export.pdf")
def export_student_pdf(
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    from reportlab.platypus import Paragraph, Spacer

    obs = list(
        db.scalars(
            select(Observation).where(Observation.student_id == student.id)
        )
    )
    styles = _pdf_styles()
    story = [
        Paragraph("Beobachtungen", styles["Title"]),
        Spacer(1, 6),
        *_student_flowables(styles, student.full_name, obs),
    ]
    audit(
        "export.pdf",
        actor=user.id,
        student_id=student.id,
        class_id=student.class_id,
        rows=len(obs),
    )
    return _pdf_response(story, student.full_name)


@router.get("/classes/{class_id}/export.pdf")
def export_class_pdf(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    obs = list(
        db.scalars(select(Observation).where(Observation.class_id == cls.id))
    )
    by_student: dict = {}
    unassigned: list = []
    for o in obs:
        if o.student_id:
            by_student.setdefault(o.student_id, []).append(o)
        else:
            unassigned.append(o)

    styles = _pdf_styles()
    story = [Paragraph(xml_escape(cls.name), styles["Title"]), Spacer(1, 10)]

    students = list(
        db.scalars(
            select(Student)
            .where(Student.class_id == cls.id, Student.active.is_(True))
            .options(selectinload(Student.aliases))
            .order_by(Student.full_name)
        )
    )
    for i, s in enumerate(students):
        if i > 0:
            story.append(PageBreak())
        story.extend(_student_flowables(styles, s.full_name, by_student.get(s.id, [])))

    if unassigned:
        story.append(PageBreak())
        story.extend(_student_flowables(styles, "Ohne Zuordnung", unassigned))

    audit("export.pdf", actor=user.id, class_id=cls.id, rows=len(obs))
    return _pdf_response(story, cls.name)
