"""A pasted class list: many pupils in one request, in one transaction."""
from app.schemas import MAX_BATCH


def _batch(client, headers, cls, names):
    return client.post(
        f"/api/classes/{cls.id}/students/batch",
        headers=headers,
        json={"students": [{"full_name": n} for n in names]},
    )


def _roster(client, headers, cls):
    return [s["full_name"] for s in client.get(f"/api/classes/{cls.id}/students", headers=headers).json()]


def test_creates_every_pupil_in_the_order_sent(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")

    res = _batch(client, headers, cls, ["Lena", "Noah", "Mia"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["full_name"] for s in body["created"]] == ["Lena", "Noah", "Mia"]
    assert all(s["active"] for s in body["created"])
    assert body["skipped"] == []
    assert sorted(_roster(client, headers, cls)) == ["Lena", "Mia", "Noah"]


def test_short_name_and_aliases_come_along(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    res = client.post(
        f"/api/classes/{cls.id}/students/batch",
        headers=auth("t@example.com"),
        json={
            "students": [
                {"full_name": "Beatrice Hunziker", "short_name": "Bea", "aliases": ["Bee"]}
            ]
        },
    )
    assert res.status_code == 200
    [created] = res.json()["created"]
    assert created["short_name"] == "Bea"
    assert [a["alias"] for a in created["aliases"]] == ["Bee"]


def test_names_already_on_the_roster_are_skipped_not_refused(
    client, make_user, make_class, make_student, auth
):
    """Uploading the list again after adding someone by hand adds the missing ones."""
    user = make_user("t@example.com")
    cls = make_class(user)
    make_student(cls, "Anna Meier")
    headers = auth("t@example.com")

    res = _batch(client, headers, cls, ["anna   MEIER", "Ben"])
    assert res.status_code == 200
    body = res.json()
    assert [s["full_name"] for s in body["created"]] == ["Ben"]
    # Reported as sent, so the PWA can name who was skipped.
    assert body["skipped"] == ["anna   MEIER"]
    assert sorted(_roster(client, headers, cls)) == ["Anna Meier", "Ben"]


def test_a_name_repeated_within_the_batch_is_created_once(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")

    body = _batch(client, headers, cls, ["Anna", "Ben", "anna"]).json()
    assert [s["full_name"] for s in body["created"]] == ["Anna", "Ben"]
    assert body["skipped"] == ["anna"]
    assert sorted(_roster(client, headers, cls)) == ["Anna", "Ben"]


def test_nothing_new_is_still_a_success(client, make_user, make_class, make_student, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    make_student(cls, "Anna Meier")
    res = _batch(client, auth("t@example.com"), cls, ["Anna Meier"])
    assert res.status_code == 200
    assert res.json() == {"created": [], "skipped": ["Anna Meier"]}


def test_names_are_trimmed(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    body = _batch(client, auth("t@example.com"), cls, ["  Anna  "]).json()
    assert body["created"][0]["full_name"] == "Anna"


def test_empty_batch_is_422(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    assert _batch(client, auth("t@example.com"), cls, []).status_code == 422


def test_oversized_batch_is_422_and_creates_nobody(client, make_user, make_class, auth):
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    names = [f"Kind {i}" for i in range(MAX_BATCH + 1)]
    assert _batch(client, headers, cls, names).status_code == 422
    assert _roster(client, headers, cls) == []


def test_one_bad_name_rejects_the_whole_batch(client, make_user, make_class, auth):
    """All or nothing: a rejected name must not leave half a class behind."""
    user = make_user("t@example.com")
    cls = make_class(user)
    headers = auth("t@example.com")
    assert _batch(client, headers, cls, ["Anna", "N" * 300, "Ben"]).status_code == 422
    assert _roster(client, headers, cls) == []
