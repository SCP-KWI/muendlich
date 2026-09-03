"""End-to-end smoke test with no cloud and no API key.

Exercises: login -> create class -> add students -> capture (Stage1->2->resolve)
-> commit -> list observations. Uses FastAPI's TestClient against whatever
DATABASE_URL is configured (sqlite by default).

Run from backend/:  python -m scripts.smoke
Assumes migrations are applied and the dev admin is seeded.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD

c = TestClient(app)


def main() -> None:
    # login
    r = c.post(
        "/api/auth/login",
        json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD},
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # pick the seeded class
    classes = c.get("/api/classes", headers=h).json()
    cls = next(x for x in classes if x["name"] == "3a Deutsch")
    cid = cls["id"]
    print(f"class: {cls['name']} ({cid})")

    # capture. Beatrice is NOT on the roster and leads her own sentence, so she
    # should come back as off_roster and be added via create_student on commit.
    raw = ("Anna was great today, helped a classmate. Beatrice was distracted. "
           "Colin got on my nerves. Darian spaced out. "
           "Felicia didn't have her homework.")
    draft = c.post(
        f"/api/classes/{cid}/captures", headers=h, json={"raw_text": raw}
    ).json()
    print(f"\ncapture_id: {draft['capture_id']}  lesson_date: {draft['lesson_date']}")
    print("proposed observations:")
    for p in draft["proposed"]:
        m = p["match"]
        print(
            f"  {p['temp_id']}: mention={p['mention']!r:12} "
            f"sentiment={p['sentiment']:8} status={m['status']:14} "
            f"conf={m['confidence']} -> {m['student_name']}"
        )

    # build a commit: save matched/low_confidence, add the off-roster one as new
    items = []
    for p in draft["proposed"]:
        st = p["match"]["status"]
        base = {
            "temp_id": p["temp_id"],
            "text": p["text"],
            "sentiment": p["sentiment"],
        }
        if st in ("matched", "low_confidence"):
            items.append({**base, "action": "save", "student_id": p["match"]["student_id"]})
        elif st == "off_roster":
            items.append({**base, "action": "create_student", "new_student_name": p["mention"]})
    commit = c.post(
        f"/api/captures/{draft['capture_id']}/commit",
        headers=h,
        json={"items": items},
    ).json()
    print(f"\ncommitted {len(commit['saved'])} observations, "
          f"created {len(commit['created_student_ids'])} student(s)")

    # verify via list endpoint
    obs = c.get(f"/api/classes/{cid}/observations", headers=h).json()
    print(f"\nobservations now in class: {len(obs)}")
    assert len(obs) == len(items), "observation count mismatch"
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
