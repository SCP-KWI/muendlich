import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ErrorBanner } from "./ErrorBanner.jsx";

// created_at is a full timestamp, not the plain YYYY-MM-DD the observation
// screens format, and it carries an offset — so render it in the teacher's own
// timezone rather than slicing the UTC string and landing a day early.
//
// Time of day included on purpose: two classes of the same name are often made
// in the same sitting, and the date alone would leave them as indistinguishable
// as the name did.
function formatCreatedAt(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("de-CH", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function ClassList({ onSelect }) {
  const [classes, setClasses] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listClasses()
      .then(setClasses)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBanner message={error} />;
  if (classes === null) return <p className="muted">Lade Klassen…</p>;
  if (classes.length === 0)
    return <p className="muted">Noch keine Klassen angelegt.</p>;

  // Names held by more than one class. Those are the only ones where a creation
  // date earns its place; everywhere else it is noise on a screen a teacher uses
  // in the thirty seconds between lessons.
  const duplicated = new Set(
    classes
      .map((c) => c.name.trim().toLowerCase())
      .filter((name, i, all) => all.indexOf(name) !== i)
  );

  return (
    <div>
      <h2>Klasse wählen</h2>
      <ul className="class-list">
        {classes.map((c) => (
          <li key={c.id}>
            <button className="class-item" onClick={() => onSelect(c)}>
              <span className="class-name">{c.name}</span>
              {c.subject && <span className="muted"> · {c.subject}</span>}
              {/* Two classes can legitimately share a name, and an accidental
                  duplicate shares everything — so the roster size is the line
                  that actually separates them ("0 Schüler/innen" is the one you
                  did not mean to pick). */}
              <span className="class-meta muted">
                {[
                  [c.semester, c.school_year].filter(Boolean).join(" "),
                  `${c.student_count} ${
                    c.student_count === 1 ? "Schüler/in" : "Schüler/innen"
                  }`,
                  // Only when the name alone is ambiguous — and it is the one
                  // thing that always differs, even between two empty twins.
                  duplicated.has(c.name.trim().toLowerCase())
                    ? `angelegt ${formatCreatedAt(c.created_at)}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
