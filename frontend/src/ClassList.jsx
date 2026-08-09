import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ErrorBanner } from "./ErrorBanner.jsx";

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

  return (
    <div>
      <h2>Klasse wählen</h2>
      <ul className="class-list">
        {classes.map((c) => (
          <li key={c.id}>
            <button className="class-item" onClick={() => onSelect(c)}>
              <span className="class-name">{c.name}</span>
              {c.subject && <span className="muted"> · {c.subject}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
