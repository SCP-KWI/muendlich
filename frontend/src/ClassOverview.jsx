import { useEffect, useState } from "react";
import { api, download, safeFilename } from "./api.js";

const EMPTY_COUNTS = { positive: 0, neutral: 0, negative: 0 };

export function ClassOverview({ klass, onSelectStudent, onBack }) {
  const [students, setStudents] = useState(null);
  const [stats, setStats] = useState(null);
  const [unassigned, setUnassigned] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    // classStats is a server-side aggregate: three counts per pupil, instead of
    // downloading every observation body for the whole school year just to tally.
    Promise.all([api.listStudents(klass.id), api.classStats(klass.id)])
      .then(([studentList, classStats]) => {
        if (cancelled) return;
        setStudents(studentList);
        setStats(
          Object.fromEntries(
            classStats.students.map((s) => [s.student_id, s.counts])
          )
        );
        setUnassigned(classStats.unassigned);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [klass.id]);

  if (error) return <p className="error">{error}</p>;
  if (students === null || stats === null) return <p className="muted">Lade…</p>;

  return (
    <div>
      <button className="link back" onClick={onBack}>
        ← Klassen
      </button>
      <h2>{klass.name}</h2>
      <div className="export-row">
        <button
          className="export"
          onClick={() =>
            download(
              `/api/classes/${klass.id}/export.csv`,
              safeFilename(`${klass.name}.csv`)
            )
          }
        >
          ⭳ CSV
        </button>
        <button
          className="export"
          onClick={() =>
            download(
              `/api/classes/${klass.id}/export.pdf`,
              safeFilename(`${klass.name}.pdf`)
            )
          }
        >
          ⭳ PDF
        </button>
      </div>

      <ul className="student-list">
        {students.map((s) => {
          const c = stats[s.id] || EMPTY_COUNTS;
          const total = c.positive + c.neutral + c.negative;
          return (
            <li key={s.id}>
              <button
                className="student-item"
                onClick={() => onSelectStudent(s)}
              >
                <span className="student-name">{s.full_name}</span>
                <span className="counts">
                  {total === 0 ? (
                    <span className="muted">keine</span>
                  ) : (
                    <>
                      {c.positive > 0 && (
                        <span className="chip pos">{c.positive}</span>
                      )}
                      {c.neutral > 0 && (
                        <span className="chip neu">{c.neutral}</span>
                      )}
                      {c.negative > 0 && (
                        <span className="chip neg">{c.negative}</span>
                      )}
                    </>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {unassigned > 0 && (
        <p className="muted">
          {unassigned} Beobachtung{unassigned === 1 ? "" : "en"} ohne Zuordnung
          (im CSV-Export enthalten).
        </p>
      )}
    </div>
  );
}
