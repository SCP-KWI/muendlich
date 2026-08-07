"""Seed a demo dataset for handbook screenshots. Runs against the scratch sqlite DB."""
import datetime as dt
import random

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import (
    Class,
    Observation,
    Sentiment,
    Student,
    StudentAlias,
    User,
    UserRole,
)

EMAIL = "m.beispiel@schule.ch"
PASSWORD = "handbuch-demo-2026"

ROSTER_3A = [
    ("Anna Meier", "Anna", ["Anni"]),
    ("Beatrice Hunziker", "Beatrice", ["Bea"]),
    ("Colin Baumann", "Colin", ["Collin"]),
    ("Darian Frei", "Darian", []),
    ("Felicia Roth", "Felicia", ["Feli"]),
    ("Jonas Wyss", "Jonas", []),
    ("Lea Bachmann", "Lea", []),
    ("Nuri Öztürk", "Nuri", []),
]

ROSTER_2B = [
    ("Elif Kaya", "Elif", []),
    ("Marco Steiner", "Marco", []),
    ("Sophie Brunner", "Sophie", ["Sophie B."]),
    ("Timo Gerber", "Timo", []),
]

# (student full_name | None, text, sentiment, days_ago, score)
OBS = [
    ("Anna Meier", "Hat heute im Unterricht Netflix geschaut und liess sich auch durch wiederholte Einwände meinerseits nicht davon überzeugen, dass der Unterricht spannender sein könnte als ihre Serie.", "negative", 1, 3.0),
    ("Anna Meier", "Erstaunlich präzise Analyse der Gretchenfrage — offenbar hat die Serienpause etwas gebracht.", "positive", 9, 5.0),
    ("Anna Meier", "War pünktlich. Das schreibe ich hier auf, weil es erwähnenswert ist.", "neutral", 16, None),
    ("Anna Meier", "Hat die Gruppenarbeit übernommen, nachdem die Gruppe kollektiv beschlossen hatte, nichts zu tun.", "positive", 23, 5.5),
    ("Colin Baumann", "Hat die Diskussion zu Faust gerettet, als sonst niemand mehr etwas sagen wollte. Starker Beitrag zum Gretchen-Problem.", "positive", 1, 5.5),
    ("Colin Baumann", "Diskutiert gern und lange. Manchmal auch mit sich selbst.", "neutral", 8, None),
    ("Colin Baumann", "Sehr aufmerksam, hat zweimal nachgefragt, bis der Begriff wirklich sass.", "positive", 15, 5.0),
    ("Darian Frei", "War körperlich anwesend.", "neutral", 1, None),
    ("Darian Frei", "Hat den Textauftrag erst nach dreimaliger Aufforderung begonnen, dann aber sauber zu Ende gebracht.", "neutral", 10, 4.0),
    ("Darian Frei", "Meldet sich nie freiwillig, antwortet aber richtig, wenn man ihn direkt fragt.", "neutral", 20, 4.5),
    ("Felicia Roth", "Hat die Hausaufgaben vergessen, dafür eine bemerkenswert kreative Erklärung geliefert, in der ein Drucker, eine Katze und ein Zugausfall vorkamen.", "negative", 1, 3.5),
    ("Felicia Roth", "Hat den Vortrag über Schillers Balladen frei gehalten und dabei die halbe Klasse wachgehalten.", "positive", 12, 5.5),
    ("Felicia Roth", "Kam zehn Minuten zu spät, mit Kaffee. Immerhin für die ganze Reihe.", "negative", 19, None),
    ("Jonas Wyss", "Hat die Diskussion mit einer sehr guten Gegenfrage in Gang gebracht.", "positive", 3, 5.0),
    ("Jonas Wyss", "Ruhig, aber die Notizen im Heft sind vorbildlich.", "positive", 14, 5.0),
    ("Lea Bachmann", "Hat drei Mal das Handy hervorgeholt, jedes Mal mit dem Argument, sie schaue nur die Zeit an. Es war 10:15, 10:17 und 10:19.", "negative", 2, 3.5),
    ("Lea Bachmann", "Sehr gute Zusammenfassung des Kapitels aus dem Stegreif.", "positive", 11, 5.5),
    ("Beatrice Hunziker", "Hat Anna beim Textverständnis geholfen, ohne dass ich fragen musste.", "positive", 1, 5.5),
    ("Beatrice Hunziker", "Stille Mitarbeit, dafür sehr präsent in der Gruppenarbeit.", "positive", 13, 5.0),
    ("Nuri Öztürk", "Hat die ganze Lektion an einem Satz gefeilt. Der Satz war am Ende sehr gut.", "positive", 4, 5.0),
    ("Nuri Öztürk", "Hausaufgaben zwar gemacht, aber offensichtlich im Bus.", "neutral", 17, 4.0),
    (None, "Jemand hat den Beamer wieder auf Portugiesisch umgestellt. Ich weiss nicht, wer.", "neutral", 5, None),
]


def run() -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            user = User(
                email=EMAIL,
                password_hash=hash_password(PASSWORD),
                role=UserRole.teacher,
            )
            db.add(user)
            db.flush()

        if db.scalar(select(Class).where(Class.user_id == user.id)) is not None:
            print("already seeded")
            return

        c3a = Class(
            user_id=user.id,
            name="3a Deutsch",
            subject="Deutsch",
            semester="FS2026",
            school_year="2025/26",
        )
        c2b = Class(
            user_id=user.id,
            name="2b Deutsch",
            subject="Deutsch",
            semester="FS2026",
            school_year="2025/26",
        )
        db.add_all([c3a, c2b])
        db.flush()

        by_name = {}
        for cls, roster in ((c3a, ROSTER_3A), (c2b, ROSTER_2B)):
            for full, short, aliases in roster:
                s = Student(
                    class_id=cls.id,
                    full_name=full,
                    short_name=short,
                    aliases=[StudentAlias(alias=a) for a in aliases],
                )
                db.add(s)
                by_name[full] = s
        db.flush()

        today = dt.date(2026, 7, 31)
        for full, text, sent, days_ago, score in OBS:
            student = by_name.get(full) if full else None
            db.add(
                Observation(
                    class_id=c3a.id,
                    student_id=student.id if student else None,
                    text=text,
                    sentiment=Sentiment(sent),
                    manual_score=score,
                    lesson_date=today - dt.timedelta(days=days_ago),
                )
            )

        db.commit()
        print(f"seeded {EMAIL} / {PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    random.seed(0)
    run()
