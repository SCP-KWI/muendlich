import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

const SENTIMENTS = [
  ["positive", "positiv"],
  ["neutral", "neutral"],
  ["negative", "negativ"],
];

// Build the initial editable state for one proposed observation.
function initItem(p) {
  const st = p.match.status;
  return {
    temp_id: p.temp_id,
    mention: p.mention,
    text: p.text,
    sentiment: p.sentiment,
    status: st,
    confidence: p.match.confidence,
    student_name: p.match.student_name,
    action:
      st === "matched" || st === "low_confidence"
        ? "save"
        : st === "off_roster"
          ? "create_student"
          : "unassigned",
    student_id: p.match.student_id,
    new_student_name: p.mention,
  };
}

export function DraftReview({ klass, draft, onDone }) {
  const [items, setItems] = useState(() => draft.proposed.map(initItem));
  const [students, setStudents] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listStudents(klass.id).then(setStudents).catch(() => {});
  }, [klass.id]);

  const needsAttention = useMemo(
    () => items.filter((i) => i.status !== "matched").length,
    [items]
  );

  function update(temp_id, patch) {
    setItems((prev) =>
      prev.map((i) => (i.temp_id === temp_id ? { ...i, ...patch } : i))
    );
  }

  async function commit() {
    if (busy || done) return; // belt and braces alongside the disabled button
    setBusy(true);
    setError(null);
    const payload = items.map((i) => {
      const base = { temp_id: i.temp_id, action: i.action };
      if (i.action === "discard") return base;
      base.text = i.text;
      base.sentiment = i.sentiment;
      if (i.action === "save" || i.action === "map_existing")
        base.student_id = i.student_id;
      if (i.action === "create_student")
        base.new_student_name = i.new_student_name;
      return base;
    });
    try {
      const result = await api.commitCapture(draft.capture_id, payload);
      setDone(true);
      onDone(result);
    } catch (err) {
      // 409 = the backend already committed this capture (retry, double-tap, or
      // a stale tab). The save succeeded; say so rather than showing an error.
      if (err.status === 409) {
        setDone(true);
        setError(
          "Diese Aufnahme wurde bereits gespeichert. Die Beobachtungen findest du in der Übersicht."
        );
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>Prüfen &amp; speichern</h2>
      <p className="muted">
        {items.length} Beobachtung{items.length === 1 ? "" : "en"}
        {needsAttention > 0 && ` · ${needsAttention} zu klären`}
      </p>

      {draft.sent_to_cloud && (
        <details className="sent-box">
          <summary>
            {draft.anonymize_enabled
              ? "🔒 An die Cloud gesendet (anonymisiert)"
              : "⚠️ An die Cloud gesendet (nicht anonymisiert)"}
          </summary>
          <p className="sent-text">{draft.sent_to_cloud}</p>
          {draft.anonymize_enabled && (
            <p className="muted small">
              Namen wurden vor dem Versand durch Platzhalter ersetzt und danach
              lokal wiederhergestellt.
            </p>
          )}
        </details>
      )}

      <ul className="draft-list">
        {items.map((i) => (
          <li key={i.temp_id} className={`draft-item status-${i.status}`}>
            <div className="draft-head">
              <strong>{i.mention}</strong>
              {i.status === "matched" && i.student_name && (
                <span className="badge ok">→ {i.student_name}</span>
              )}
              {i.status === "low_confidence" && (
                <span className="badge warn">
                  unsicher{i.student_name ? ` → ${i.student_name}` : ""}
                </span>
              )}
              {i.status === "off_roster" && (
                <span className="badge warn">nicht auf der Liste</span>
              )}
            </div>

            <textarea
              className="draft-text"
              value={i.text}
              onChange={(e) => update(i.temp_id, { text: e.target.value })}
              rows={2}
            />

            <div className="draft-controls">
              <select
                value={i.sentiment}
                onChange={(e) =>
                  update(i.temp_id, { sentiment: e.target.value })
                }
              >
                {SENTIMENTS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>

              <select
                value={i.action}
                onChange={(e) => update(i.temp_id, { action: e.target.value })}
              >
                {(i.status === "matched" || i.status === "low_confidence") && (
                  <option value="save">
                    Speichern{i.student_name ? ` (${i.student_name})` : ""}
                  </option>
                )}
                <option value="create_student">Als neue/n Schüler/in</option>
                <option value="map_existing">Zuordnen zu…</option>
                <option value="unassigned">Ohne Zuordnung</option>
                <option value="discard">Verwerfen</option>
              </select>
            </div>

            {i.action === "create_student" && (
              <input
                className="draft-name"
                value={i.new_student_name}
                onChange={(e) =>
                  update(i.temp_id, { new_student_name: e.target.value })
                }
                placeholder="Name der/des neuen Schüler/in"
              />
            )}

            {i.action === "map_existing" && (
              <select
                className="draft-name"
                value={i.student_id || ""}
                onChange={(e) =>
                  update(i.temp_id, { student_id: e.target.value })
                }
              >
                <option value="">— auswählen —</option>
                {students.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.full_name}
                  </option>
                ))}
              </select>
            )}
          </li>
        ))}
      </ul>

      {error && <p className="error">{error}</p>}

      <button className="primary" onClick={commit} disabled={busy || done}>
        {busy ? "Speichere…" : done ? "Gespeichert" : "Speichern"}
      </button>
    </div>
  );
}
