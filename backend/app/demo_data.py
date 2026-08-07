"""The dataset every demo visitor starts from.

Pure data, no database access — app/demo.py copies this into a fresh user on
each demo login. Keep it small: it is written once per visitor, and a demo that
opens on an empty screen sells nothing, while one that opens on 200 rows buries
the point.

The pupils are invented. Observation dates are relative to the day the session
starts, so the overview always looks recently used.
"""

# (name, short_name, aliases) — aliases exercise the matcher on the names a
# teacher actually dictates.
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

CLASSES = [
    # (name, subject, semester, school_year, roster)
    ("3a Deutsch", "Deutsch", "FS2026", "2025/26", ROSTER_3A),
    ("2b Deutsch", "Deutsch", "FS2026", "2025/26", ROSTER_2B),
]

# (class name, pupil full_name | None, text, sentiment, days_ago, manual_score)
# A None pupil is an unassigned observation — the state the review screen exists
# to resolve, so the demo should contain at least one.
OBSERVATIONS = [
    ("3a Deutsch", "Anna Meier", "Erstaunlich präzise Analyse der Gretchenfrage.", "positive", 2, 5.0),
    ("3a Deutsch", "Anna Meier", "Hat die Gruppenarbeit übernommen, nachdem die Gruppe kollektiv beschlossen hatte, nichts zu tun.", "positive", 9, 5.5),
    ("3a Deutsch", "Anna Meier", "War pünktlich. Das schreibe ich hier auf, weil es erwähnenswert ist.", "neutral", 16, None),
    ("3a Deutsch", "Colin Baumann", "Hat die Diskussion zu Faust gerettet, als sonst niemand mehr etwas sagen wollte.", "positive", 1, 5.5),
    ("3a Deutsch", "Colin Baumann", "Diskutiert gern und lange. Manchmal auch mit sich selbst.", "neutral", 8, None),
    ("3a Deutsch", "Darian Frei", "Meldet sich nie freiwillig, antwortet aber richtig, wenn man ihn direkt fragt.", "neutral", 3, 4.5),
    ("3a Deutsch", "Darian Frei", "Hat den Textauftrag erst nach dreimaliger Aufforderung begonnen, dann aber sauber zu Ende gebracht.", "neutral", 10, 4.0),
    ("3a Deutsch", "Felicia Roth", "Hausaufgaben vergessen, dafür eine bemerkenswert kreative Erklärung mit Drucker, Katze und Zugausfall.", "negative", 1, 3.5),
    ("3a Deutsch", "Felicia Roth", "Hat den Vortrag über Schillers Balladen frei gehalten und dabei die halbe Klasse wachgehalten.", "positive", 12, 5.5),
    ("3a Deutsch", "Jonas Wyss", "Hat die Diskussion mit einer sehr guten Gegenfrage in Gang gebracht.", "positive", 4, 5.0),
    ("3a Deutsch", "Lea Bachmann", "Dreimal das Handy hervorgeholt, jedes Mal mit dem Argument, sie schaue nur die Zeit an.", "negative", 2, 3.5),
    ("3a Deutsch", "Lea Bachmann", "Sehr gute Zusammenfassung des Kapitels aus dem Stegreif.", "positive", 11, 5.5),
    ("3a Deutsch", "Beatrice Hunziker", "Hat Anna beim Textverständnis geholfen, ohne dass ich fragen musste.", "positive", 1, 5.5),
    ("3a Deutsch", "Nuri Öztürk", "Hat die ganze Lektion an einem Satz gefeilt. Der Satz war am Ende sehr gut.", "positive", 5, 5.0),
    ("3a Deutsch", None, "Jemand hat den Beamer wieder auf Portugiesisch umgestellt. Ich weiss nicht, wer.", "neutral", 5, None),
    ("2b Deutsch", "Elif Kaya", "Sehr sorgfältige Textarbeit, hat zwei Stilfehler selbst gefunden.", "positive", 2, 5.0),
    ("2b Deutsch", "Marco Steiner", "Unruhig, hat aber beim Diktat konzentriert mitgemacht.", "neutral", 2, 4.0),
    ("2b Deutsch", "Sophie Brunner", "Hat die Gruppe moderiert und alle zu Wort kommen lassen.", "positive", 6, 5.5),
    ("2b Deutsch", "Timo Gerber", "Hat den Auftrag nicht verstanden und auch nicht nachgefragt.", "negative", 6, 3.5),
]
