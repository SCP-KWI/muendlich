"""Input validation: every one of these used to reach the database and 500."""
import pytest


def test_invalid_sentiment_filter_is_422_not_500(
    client, auth, make_user, make_class
):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.get(
        f"/api/classes/{cls.id}/observations?sentiment=bogus",
        headers=auth("t@example.com"),
    )
    assert res.status_code == 422, res.text


def test_valid_sentiment_filter_works(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    make_observation(cls, student, sentiment="positive")
    make_observation(cls, student, text="Störte", sentiment="negative")

    res = client.get(
        f"/api/classes/{cls.id}/observations?sentiment=negative",
        headers=auth("t@example.com"),
    )
    assert res.status_code == 200
    assert [o["sentiment"] for o in res.json()] == ["negative"]


# ---- explicit null on NOT NULL columns ----
@pytest.mark.parametrize("field", ["full_name", "active"])
def test_explicit_null_on_student_not_null_column_is_422(
    client, auth, make_user, make_class, make_student, field
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    res = client.patch(
        f"/api/students/{student.id}",
        headers=auth("t@example.com"),
        json={field: None},
    )
    assert res.status_code == 422, res.text


def test_explicit_null_on_class_name_is_422(
    client, auth, make_user, make_class
):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.patch(
        f"/api/classes/{cls.id}", headers=auth("t@example.com"), json={"name": None}
    )
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("field", ["text", "sentiment"])
def test_explicit_null_on_observation_not_null_column_is_422(
    client, auth, make_user, make_class, make_student, make_observation, field
):
    user = make_user("t@example.com")
    cls = make_class(user)
    obs = make_observation(cls, make_student(cls))
    res = client.patch(
        f"/api/observations/{obs.id}",
        headers=auth("t@example.com"),
        json={field: None},
    )
    assert res.status_code == 422, res.text


def test_nullable_fields_can_still_be_cleared(
    client, auth, make_user, make_class, make_student, make_observation
):
    """manual_score and student_id ARE nullable — explicit null must work."""
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    obs = make_observation(cls, student, manual_score=4.5)

    res = client.patch(
        f"/api/observations/{obs.id}",
        headers=auth("t@example.com"),
        json={"manual_score": None, "student_id": None},
    )
    assert res.status_code == 200, res.text
    assert res.json()["manual_score"] is None
    assert res.json()["student_id"] is None


def test_omitted_fields_are_left_alone(
    client, auth, make_user, make_class, make_student
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls, full_name="Anna Meier")
    res = client.patch(
        f"/api/students/{student.id}",
        headers=auth("t@example.com"),
        json={"short_name": "Anni"},
    )
    assert res.status_code == 200
    assert res.json()["full_name"] == "Anna Meier"
    assert res.json()["short_name"] == "Anni"


# ---- manual_score domain ----
@pytest.mark.parametrize("score", [0, 0.5, 6.5, 7, -2, 1e9, 4.37, 4.1, "abc"])
def test_out_of_domain_manual_score_is_422(
    client, auth, make_user, make_class, make_student, make_observation, score
):
    user = make_user("t@example.com")
    cls = make_class(user)
    obs = make_observation(cls, make_student(cls))
    res = client.patch(
        f"/api/observations/{obs.id}",
        headers=auth("t@example.com"),
        json={"manual_score": score},
    )
    assert res.status_code == 422, f"score={score!r} → {res.status_code}"


@pytest.mark.parametrize("score", [1, 1.5, 4, 4.5, 6])
def test_valid_half_marks_are_accepted(
    client, auth, make_user, make_class, make_student, make_observation, score
):
    user = make_user("t@example.com")
    cls = make_class(user)
    obs = make_observation(cls, make_student(cls))
    res = client.patch(
        f"/api/observations/{obs.id}",
        headers=auth("t@example.com"),
        json={"manual_score": score},
    )
    assert res.status_code == 200, f"score={score!r}: {res.text}"
    assert res.json()["manual_score"] == float(score)


def test_out_of_domain_score_rejected_at_commit(
    client, auth, make_user, make_class, make_student
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    draft = client.post(
        f"/api/classes/{cls.id}/captures",
        headers=auth("t@example.com"),
        json={"raw_text": "Anna war gut."},
    )
    capture_id = draft.json()["capture_id"]
    res = client.post(
        f"/api/captures/{capture_id}/commit",
        headers=auth("t@example.com"),
        json={
            "items": [
                {
                    "temp_id": "o1",
                    "action": "save",
                    "text": "gut",
                    "sentiment": "positive",
                    "student_id": str(student.id),
                    "manual_score": 99,
                }
            ]
        },
    )
    assert res.status_code == 422, res.text


# ---- length caps ----
def test_oversized_raw_text_is_422(client, auth, make_user, make_class):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.post(
        f"/api/classes/{cls.id}/captures",
        headers=auth("t@example.com"),
        json={"raw_text": "x" * 9_000},
    )
    assert res.status_code == 422


def test_empty_raw_text_is_422(client, auth, make_user, make_class):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.post(
        f"/api/classes/{cls.id}/captures",
        headers=auth("t@example.com"),
        json={"raw_text": "   "},
    )
    assert res.status_code == 422


def test_oversized_names_are_422(client, auth, make_user, make_class):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.post(
        f"/api/classes/{cls.id}/students",
        headers=auth("t@example.com"),
        json={"full_name": "N" * 300},
    )
    assert res.status_code == 422


def test_pagination_is_bounded(
    client, auth, make_user, make_class, make_student, make_observation
):
    user = make_user("t@example.com")
    cls = make_class(user)
    student = make_student(cls)
    for i in range(5):
        make_observation(cls, student, text=f"Notiz {i}")

    res = client.get(
        f"/api/classes/{cls.id}/observations?limit=2", headers=auth("t@example.com")
    )
    assert res.status_code == 200
    assert len(res.json()) == 2

    # A caller asking for more than max_page_size gets clamped, not 500s.
    res = client.get(
        f"/api/classes/{cls.id}/observations?limit=100000",
        headers=auth("t@example.com"),
    )
    assert res.status_code == 200
    assert len(res.json()) == 5


def test_health_does_not_leak_configuration(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert "anonymize_enabled" not in res.text
