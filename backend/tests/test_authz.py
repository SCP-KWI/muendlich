"""Cross-tenant isolation: teacher A must never reach teacher B's data.

Every endpoint that takes a resource id is covered. All of them must answer 404
(not 403) so probing reveals nothing about whether the id exists.
"""
import uuid

import pytest


def test_login_required_everywhere(client, two_teachers):
    """No authenticated identity → 403 from the bearer scheme, never 200."""
    t = two_teachers
    paths = [
        ("GET", "/api/classes"),
        ("GET", f"/api/classes/{t['cls_a'].id}"),
        ("GET", f"/api/classes/{t['cls_a'].id}/students"),
        ("POST", f"/api/classes/{t['cls_a'].id}/students/batch"),
        ("GET", f"/api/classes/{t['cls_a'].id}/observations"),
        ("GET", f"/api/classes/{t['cls_a'].id}/stats"),
        ("GET", f"/api/classes/{t['cls_a'].id}/export.csv"),
        ("GET", f"/api/students/{t['stu_a'].id}/summary"),
        ("GET", "/api/me"),
    ]
    for method, path in paths:
        res = client.request(method, path)
        assert res.status_code in (401, 403), f"{method} {path} → {res.status_code}"


@pytest.mark.parametrize(
    "method,template",
    [
        ("GET", "/api/classes/{cls_b}"),
        ("PATCH", "/api/classes/{cls_b}"),
        ("DELETE", "/api/classes/{cls_b}"),
        ("GET", "/api/classes/{cls_b}/students"),
        ("POST", "/api/classes/{cls_b}/students"),
        ("POST", "/api/classes/{cls_b}/students/batch"),
        ("GET", "/api/classes/{cls_b}/observations"),
        ("GET", "/api/classes/{cls_b}/stats"),
        ("GET", "/api/classes/{cls_b}/export.csv"),
        ("GET", "/api/classes/{cls_b}/export.pdf"),
        ("POST", "/api/classes/{cls_b}/captures"),
        ("GET", "/api/students/{stu_b}/observations"),
        ("GET", "/api/students/{stu_b}/summary"),
        ("GET", "/api/students/{stu_b}/export.csv"),
        ("GET", "/api/students/{stu_b}/export.pdf"),
        ("PATCH", "/api/students/{stu_b}"),
        ("DELETE", "/api/students/{stu_b}"),
        ("POST", "/api/students/{stu_b}/aliases"),
        ("PATCH", "/api/observations/{obs_b}"),
        ("DELETE", "/api/observations/{obs_b}"),
    ],
)
def test_other_teachers_resources_are_404(client, auth, two_teachers, method, template):
    t = two_teachers
    path = template.format(
        cls_b=t["cls_b"].id, stu_b=t["stu_b"].id, obs_b=t["obs_b"].id
    )
    # Send a body that would be valid if authorization passed, so a 422 can't
    # mask a missing ownership check.
    bodies = {
        "POST": {
            "captures": {"raw_text": "Bruno war gut."},
            # Before "students": the lookup below is by substring, and the
            # batch path contains it.
            "students/batch": {"students": [{"full_name": "Neu Kind"}]},
            "students": {"full_name": "Neu Kind"},
            "aliases": {"alias": "Bruni"},
        },
        "PATCH": {
            "classes": {"name": "gekapert"},
            "students": {"full_name": "gekapert"},
            "observations": {"text": "gekapert"},
        },
    }
    body = None
    if method in bodies:
        for key, payload in bodies[method].items():
            if key in path:
                body = payload
                break

    res = client.request(method, path, headers=auth("a@example.com"), json=body)
    assert res.status_code == 404, f"{method} {path} → {res.status_code}: {res.text}"


def test_own_resources_are_reachable(client, auth, two_teachers):
    """Counterpart to the above: the same shapes work on your own data."""
    t = two_teachers
    headers = auth("a@example.com")
    for path in [
        f"/api/classes/{t['cls_a'].id}",
        f"/api/classes/{t['cls_a'].id}/students",
        f"/api/classes/{t['cls_a'].id}/observations",
        f"/api/classes/{t['cls_a'].id}/stats",
        f"/api/students/{t['stu_a'].id}/summary",
    ]:
        res = client.get(path, headers=headers)
        assert res.status_code == 200, f"{path} → {res.status_code}: {res.text}"


def test_class_list_is_scoped_to_owner(client, auth, two_teachers):
    res = client.get("/api/classes", headers=auth("a@example.com"))
    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert names == ["A-Klasse"]


def test_cannot_move_observation_to_another_class_student(client, auth, two_teachers):
    """PATCH student_id must reject a pupil from a class you don't own."""
    t = two_teachers
    res = client.patch(
        f"/api/observations/{t['obs_a'].id}",
        headers=auth("a@example.com"),
        json={"student_id": str(t["stu_b"].id)},
    )
    assert res.status_code == 404


def test_cannot_commit_capture_with_other_class_student(
    client, auth, two_teachers
):
    t = two_teachers
    draft = client.post(
        f"/api/classes/{t['cls_a'].id}/captures",
        headers=auth("a@example.com"),
        json={"raw_text": "Anna war gut."},
    )
    assert draft.status_code == 201
    capture_id = draft.json()["capture_id"]

    res = client.post(
        f"/api/captures/{capture_id}/commit",
        headers=auth("a@example.com"),
        json={
            "items": [
                {
                    "temp_id": "o1",
                    "action": "map_existing",
                    "text": "Fremdes Kind",
                    "sentiment": "positive",
                    "student_id": str(t["stu_b"].id),
                }
            ]
        },
    )
    assert res.status_code == 404


def test_cannot_commit_another_teachers_capture(client, auth, two_teachers):
    t = two_teachers
    draft = client.post(
        f"/api/classes/{t['cls_b'].id}/captures",
        headers=auth("b@example.com"),
        json={"raw_text": "Bruno war gut."},
    )
    capture_id = draft.json()["capture_id"]

    res = client.post(
        f"/api/captures/{capture_id}/commit",
        headers=auth("a@example.com"),
        json={"items": []},
    )
    assert res.status_code == 404


def test_cannot_delete_another_teachers_alias(client, auth, db, two_teachers):
    from app.models import StudentAlias

    t = two_teachers
    alias = StudentAlias(student_id=t["stu_b"].id, alias="Bruni")
    db.add(alias)
    db.commit()

    res = client.delete(
        f"/api/aliases/{alias.id}", headers=auth("a@example.com")
    )
    assert res.status_code == 404
    assert db.get(StudentAlias, alias.id) is not None


def test_unknown_ids_are_404_not_500(client, auth, two_teachers):
    ghost = uuid.uuid4()
    headers = auth("a@example.com")
    for path in [
        f"/api/classes/{ghost}",
        f"/api/students/{ghost}/summary",
        f"/api/aliases/{ghost}",
    ]:
        res = client.get(path, headers=headers) if "aliases" not in path else client.delete(path, headers=headers)
        assert res.status_code == 404
