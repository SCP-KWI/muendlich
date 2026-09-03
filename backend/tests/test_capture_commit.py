"""Capture commit: replay protection, actions, and raw-text minimization."""
import uuid

from sqlalchemy import select

from app.models import CaptureStatus, Observation, RawCapture, Student


def _draft(client, headers, cls, text="Anna war heute super. Colin störte."):
    res = client.post(
        f"/api/classes/{cls.id}/captures", headers=headers, json={"raw_text": text}
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_commit_is_not_replayable(
    client, auth, make_user, make_class, make_student, db
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls, "Anna Meier")
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls)

    payload = {
        "items": [
            {
                "temp_id": "o1",
                "action": "save",
                "text": "War super.",
                "sentiment": "positive",
                "student_id": str(student.id),
            }
        ]
    }
    first = client.post(
        f"/api/captures/{draft['capture_id']}/commit", headers=headers, json=payload
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["saved"]) == 1

    # Double-tap / retry / stale tab.
    second = client.post(
        f"/api/captures/{draft['capture_id']}/commit", headers=headers, json=payload
    )
    assert second.status_code == 409, second.text

    # Exactly one observation exists, not two.
    assert len(db.scalars(select(Observation)).all()) == 1


def test_replay_does_not_duplicate_created_students(
    client, auth, make_user, make_class, db
):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls)

    payload = {
        "items": [
            {
                "temp_id": "o1",
                "action": "create_student",
                "text": "Neu hier.",
                "sentiment": "neutral",
                "new_student_name": "Zoe Neu",
            }
        ]
    }
    assert client.post(
        f"/api/captures/{draft['capture_id']}/commit", headers=headers, json=payload
    ).status_code == 200
    assert client.post(
        f"/api/captures/{draft['capture_id']}/commit", headers=headers, json=payload
    ).status_code == 409

    zoes = db.scalars(select(Student).where(Student.full_name == "Zoe Neu")).all()
    assert len(zoes) == 1


def test_commit_clears_verbatim_dictation(
    client, auth, make_user, make_class, make_student, db
):
    """Data minimization: raw_text has served its purpose once committed."""
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls, "Anna Meier")
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls, "Anna war heute wirklich sehr aufmerksam.")

    capture = db.get(RawCapture, uuid.UUID(draft["capture_id"]))
    db.refresh(capture)
    assert capture.raw_text != ""

    client.post(
        f"/api/captures/{draft['capture_id']}/commit",
        headers=headers,
        json={
            "items": [
                {
                    "temp_id": "o1",
                    "action": "save",
                    "text": "War aufmerksam.",
                    "sentiment": "positive",
                    "student_id": str(student.id),
                }
            ]
        },
    )
    db.expire_all()
    capture = db.get(RawCapture, uuid.UUID(draft["capture_id"]))
    assert capture.raw_text == ""
    assert capture.anonymized_text is None
    assert capture.status is CaptureStatus.committed


def test_discard_and_unassigned_actions(
    client, auth, make_user, make_class, make_student, db
):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls)

    res = client.post(
        f"/api/captures/{draft['capture_id']}/commit",
        headers=headers,
        json={
            "items": [
                {"temp_id": "o1", "action": "discard"},
                {
                    "temp_id": "o2",
                    "action": "unassigned",
                    "text": "Jemand störte.",
                    "sentiment": "negative",
                },
            ]
        },
    )
    assert res.status_code == 200, res.text
    saved = res.json()["saved"]
    assert len(saved) == 1
    assert saved[0]["student_id"] is None


def test_save_without_student_id_is_422(
    client, auth, make_user, make_class
):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls)
    res = client.post(
        f"/api/captures/{draft['capture_id']}/commit",
        headers=headers,
        json={
            "items": [
                {
                    "temp_id": "o1",
                    "action": "save",
                    "text": "x",
                    "sentiment": "positive",
                }
            ]
        },
    )
    assert res.status_code == 422


def test_failed_commit_leaves_capture_uncommitted(
    client, auth, make_user, make_class, db
):
    """A rejected item must not consume the capture."""
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    draft = _draft(client, headers, cls)
    capture_id = draft["capture_id"]

    bad = client.post(
        f"/api/captures/{capture_id}/commit",
        headers=headers,
        json={
            "items": [
                {"temp_id": "o1", "action": "save", "text": "x", "sentiment": "positive"}
            ]
        },
    )
    assert bad.status_code == 422

    # The teacher can fix the payload and retry — the capture is still usable.
    student = Student(class_id=cls.id, full_name="Anna Meier")
    db.add(student)
    db.commit()
    good = client.post(
        f"/api/captures/{capture_id}/commit",
        headers=headers,
        json={
            "items": [
                {
                    "temp_id": "o1",
                    "action": "save",
                    "text": "x",
                    "sentiment": "positive",
                    "student_id": str(student.id),
                }
            ]
        },
    )
    assert good.status_code == 200, good.text
