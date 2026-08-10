"""Telling classes apart, and not creating them twice by accident."""
from app.routers.classes import DUPLICATE_NAME_CODE

BODY = {"name": "3a Deutsch", "subject": "Deutsch"}


def _create(client, headers, **overrides):
    return client.post("/api/classes", json={**BODY, **overrides}, headers=headers)


# ---- duplicate names ----
def test_second_class_with_the_same_name_is_refused(client, make_user, auth):
    make_user("t@example.com")
    headers = auth("t@example.com")

    assert _create(client, headers).status_code == 201

    res = _create(client, headers)
    assert res.status_code == 409
    detail = res.json()["detail"]
    # Structured, so the PWA can offer to go ahead instead of showing a dead end.
    assert detail["code"] == DUPLICATE_NAME_CODE
    assert "3a Deutsch" in detail["message"]

    assert len(client.get("/api/classes", headers=headers).json()) == 1


def test_duplicate_check_ignores_case(client, make_user, auth):
    make_user("t@example.com")
    headers = auth("t@example.com")
    _create(client, headers)
    assert _create(client, headers, name="3A DEUTSCH").status_code == 409


def test_a_duplicate_can_be_created_deliberately(client, make_user, auth):
    """Same name, next semester, is a real thing teachers do."""
    make_user("t@example.com")
    headers = auth("t@example.com")
    _create(client, headers, semester="HS2026")

    res = _create(client, headers, semester="FS2027", allow_duplicate=True)
    assert res.status_code == 201
    assert len(client.get("/api/classes", headers=headers).json()) == 2


def test_the_name_check_is_per_teacher(client, make_user, auth):
    make_user("a@example.com")
    make_user("b@example.com")
    assert _create(client, auth("a@example.com")).status_code == 201
    # B's classes are none of A's business, and vice versa.
    assert _create(client, auth("b@example.com")).status_code == 201


def test_allow_duplicate_is_not_stored_as_a_field(client, make_user, auth):
    make_user("t@example.com")
    headers = auth("t@example.com")
    res = _create(client, headers, allow_duplicate=True)
    assert res.status_code == 201
    assert "allow_duplicate" not in res.json()


# ---- pupil counts ----
def test_class_list_reports_pupil_counts(
    client, make_user, make_class, make_student, auth
):
    user = make_user("t@example.com")
    full = make_class(user, "3a Deutsch")
    make_class(user, "2b Deutsch")  # deliberately empty
    make_student(full, "Anna Meier")
    make_student(full, "Colin Baumann")

    by_name = {c["name"]: c for c in client.get("/api/classes", headers=auth("t@example.com")).json()}
    # The whole point: an accidental duplicate is the one with nobody in it.
    assert by_name["3a Deutsch"]["student_count"] == 2
    assert by_name["2b Deutsch"]["student_count"] == 0


def test_created_class_reports_zero_pupils(client, make_user, auth):
    make_user("t@example.com")
    assert _create(client, auth("t@example.com")).json()["student_count"] == 0


def test_single_class_and_patch_also_report_the_count(
    client, make_user, make_class, make_student, auth
):
    user = make_user("t@example.com")
    cls = make_class(user, "3a Deutsch")
    make_student(cls, "Anna Meier")
    headers = auth("t@example.com")

    assert client.get(f"/api/classes/{cls.id}", headers=headers).json()["student_count"] == 1
    patched = client.patch(
        f"/api/classes/{cls.id}", json={"subject": "Französisch"}, headers=headers
    )
    assert patched.json()["student_count"] == 1


def test_class_out_carries_a_creation_timestamp(client, make_user, auth):
    """Last-resort discriminator when two classes share a name and a roster size."""
    make_user("t@example.com")
    body = _create(client, auth("t@example.com")).json()
    assert body["created_at"]
