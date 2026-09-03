"""Export hardening: formula injection, ReportLab markup, filename headers."""
import csv
import io

import pytest


def _rows(csv_bytes: bytes) -> list[dict]:
    text = csv_bytes.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


# ---- CSV formula injection ----
@pytest.mark.parametrize(
    "payload",
    [
        '=cmd|\' /c calc\'!A0',
        "+1+1",
        "-2+3",
        "@SUM(A1:A9)",
        "\t=1+1",
    ],
)
def test_csv_export_neutralises_formulas(
    client, auth, make_user, make_class, make_student, make_observation, payload
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    make_observation(cls, student, text=payload)

    res = client.get(
        f"/api/classes/{cls.id}/export.csv", headers=auth("t@example.com")
    )
    assert res.status_code == 200
    rows = _rows(res.content)
    assert len(rows) == 1
    # Prefixed with an apostrophe → Excel treats it as text, not a formula.
    assert rows[0]["text"].startswith("'")
    assert rows[0]["text"] == "'" + payload


def test_csv_export_neutralises_formula_in_student_name(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls, full_name="=HYPERLINK(\"http://evil\")")
    make_observation(cls, student)

    res = client.get(
        f"/api/students/{student.id}/export.csv", headers=auth("t@example.com")
    )
    assert res.status_code == 200
    assert _rows(res.content)[0]["student"].startswith("'")


def test_csv_export_leaves_benign_text_alone(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    make_observation(cls, student, text="Hat Beatrice geholfen; sehr gut.")

    res = client.get(
        f"/api/classes/{cls.id}/export.csv", headers=auth("t@example.com")
    )
    rows = _rows(res.content)
    # The ';' must survive as data, not split the row.
    assert rows[0]["text"] == "Hat Beatrice geholfen; sehr gut."


# ---- PDF markup escaping ----
@pytest.mark.parametrize(
    "payload",
    [
        # Benign text that merely contains markup characters. ReportLab 5's
        # parser tolerates these, but they must not be interpreted either.
        "Note < 4 diesmal",
        "Mia & Tim haben zusammengearbeitet",
        "a < b & c > d",
        # Balanced markup: silently *rendered* without escaping, letting a
        # dictation restyle the report.
        "<b>fett</b> gemeint",
        "<font color='red'>injected</font>",
        # Unbalanced markup: raises ValueError in the parser -> 500, and one
        # such observation breaks the whole class PDF.
        "<b>unclosed",
        "</para><para>",
        # Local file read: ReportLab's <img> opens the given path and embeds the
        # bytes in the PDF. Unescaped, an observation can exfiltrate any file
        # the backend process can read.
        '<img src="/etc/passwd"/>',
        '<img src="/proc/self/environ"/>',
        # Same primitive pointed at a URL — a request from inside the network.
        '<img src="http://169.254.169.254/latest/meta-data/"/>',
        # Requires a host-provided callback; raises AttributeError unescaped.
        '<onDraw name="evil"/>',
    ],
)
def test_pdf_export_neutralises_reportlab_markup(
    client, auth, make_user, make_class, make_student, make_observation, payload
):
    """ReportLab parses Paragraph text as its own markup.

    Unescaped, observation text is not merely data: <img> reads local files,
    <onDraw> invokes callbacks, and unbalanced tags raise in the parser. All of
    it must arrive as literal text.
    """
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    make_observation(cls, student, text=payload)

    res = client.get(
        f"/api/classes/{cls.id}/export.pdf", headers=auth("t@example.com")
    )
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"%PDF")


def test_pdf_export_does_not_read_local_files(
    client, auth, make_user, make_class, make_student, make_observation, tmp_path
):
    """The <img> primitive must not reach the filesystem at all."""
    from PIL import Image

    secret = tmp_path / "secret.png"
    Image.new("RGB", (60, 60), (7, 7, 7)).save(secret)
    baseline_len = None

    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    obs = make_observation(cls, student, text="harmless")
    res = client.get(f"/api/classes/{cls.id}/export.pdf", headers=auth("t@example.com"))
    baseline_len = len(res.content)

    # Same document, but the observation now points at a real readable image.
    client.patch(
        f"/api/observations/{obs.id}",
        headers=auth("t@example.com"),
        json={"text": f'<img src="{secret}" width="60" height="60"/>'},
    )
    res = client.get(f"/api/classes/{cls.id}/export.pdf", headers=auth("t@example.com"))
    assert res.status_code == 200
    # An embedded 60x60 image would inflate the PDF well beyond the text-only
    # baseline; escaped, the payload is just a slightly longer string.
    assert len(res.content) - baseline_len < 500, "image data appears to be embedded"


def test_pdf_export_survives_markup_in_names(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user, name="Klasse <script> & Co")
    student = make_student(cls, full_name="Tim & Anna <b>")
    make_observation(cls, student)

    for path in (f"/api/classes/{cls.id}/export.pdf", f"/api/students/{student.id}/export.pdf"):
        res = client.get(path, headers=auth("t@example.com"))
        assert res.status_code == 200, f"{path}: {res.text}"
        assert res.content.startswith(b"%PDF")


# ---- Content-Disposition ----
@pytest.mark.parametrize(
    "class_name",
    [
        "Klasse Müller",         # latin-1 encodable
        "Klasa Łódź",            # NOT latin-1 encodable — used to raise on encode
        'Klasse "Anführung"',    # quote would break the quoted-string
        "Klasse/mit/Slash",
        "Klasse\r\nInjected: x",  # header injection attempt
        "3a Deutsch",
    ],
)
def test_content_disposition_is_safe(
    client, auth, make_user, make_class, make_student, make_observation, class_name
):
    user = make_user("t@example.com")
    cls = make_class(user, name=class_name)
    student = make_student(cls)
    make_observation(cls, student)

    for ext in ("csv", "pdf"):
        res = client.get(
            f"/api/classes/{cls.id}/export.{ext}", headers=auth("t@example.com")
        )
        assert res.status_code == 200, res.text
        disposition = res.headers["content-disposition"]
        # Header must be latin-1 clean, single-line, and carry both forms.
        disposition.encode("latin-1")
        assert "\r" not in disposition and "\n" not in disposition
        assert disposition.startswith("attachment; filename=")
        assert "filename*=UTF-8''" in disposition
        assert disposition.count('"') == 2  # exactly the ASCII fallback's quotes


def test_content_disposition_preserves_readable_name(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user, name="3a Deutsch")
    make_observation(cls, make_student(cls))

    res = client.get(f"/api/classes/{cls.id}/export.csv", headers=auth("t@example.com"))
    assert 'filename="3a_Deutsch.csv"' in res.headers["content-disposition"]


def test_exports_are_not_cached(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user)
    make_observation(cls, make_student(cls))
    res = client.get(f"/api/classes/{cls.id}/export.csv", headers=auth("t@example.com"))
    assert res.headers["cache-control"] == "no-store, private"
