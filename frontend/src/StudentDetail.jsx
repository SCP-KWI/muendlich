import { useCallback, useEffect, useState } from "react";
import { api, download, safeFilename } from "./api.js";

const SENTIMENTS = [
  ["positive", "positiv"],
  ["neutral", "neutral"],
  ["negative", "negativ"],
];

function fmtDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

// Recomputed locally after an edit so a one-field change doesn't cost a full
// round-trip of the pupil's history.
function tally(timeline) {
  const counts = { positive: 0, neutral: 0, negative: 0 };
  const scores = [];
  for (const o of timeline) {
    counts[o.sentiment] += 1;
    if (o.manual_score !== null && o.manual_score !== undefined) {
      scores.push(o.manual_score);
    }
  }
  const avg = scores.length
    ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 100) / 100
    : null;
  return { counts, avg, count: timeline.length };
}

export function StudentDetail({ student, onBack, backLabel }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api
      .studentSummary(student.id)
      .then(setSummary)
      .catch((e) => setError(e.message));
  }, [student.id]);

  useEffect(load, [load]);

  // Apply the PATCH response to local state instead of refetching everything.
  function applyLocal(updater) {
    setSummary((prev) => {
      if (!prev) return prev;
      const timeline = updater(prev.timeline);
      const { counts, avg, count } = tally(timeline);
      return { ...prev, timeline, counts, avg_score: avg, count };
    });
  }

  async function save(id, patch) {
    setError(null);
    try {
      const updated = await api.updateObservation(id, patch);
      applyLocal((timeline) =>
        timeline.map((o) => (o.id === id ? updated : o))
      );
    } catch (e) {
      setError(e.message);
      load(); // re-sync after a rejected edit
    }
  }

  async function remove(id) {
    if (!confirm("Diese Beobachtung löschen?")) return;
    setError(null);
    try {
      await api.deleteObservation(id);
      applyLocal((timeline) => timeline.filter((o) => o.id !== id));
    } catch (e) {
      setError(e.message);
      load();
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (summary === null) return <p className="muted">Lade…</p>;

  const { counts } = summary;
  const total = counts.positive + counts.neutral + counts.negative;

  return (
    <div>
      <button className="link back" onClick={onBack}>
        ← {backLabel}
      </button>
      <h2>{summary.full_name}</h2>
      <div className="export-row">
        <button
          className="export"
          onClick={() =>
            download(
              `/api/students/${student.id}/export.csv`,
              safeFilename(`${summary.full_name}.csv`)
            )
          }
        >
          ⭳ CSV
        </button>
        <button
          className="export"
          onClick={() =>
            download(
              `/api/students/${student.id}/export.pdf`,
              safeFilename(`${summary.full_name}.pdf`)
            )
          }
        >
          ⭳ PDF
        </button>
      </div>

      {/* trend summary */}
      <div className="trend">
        {total === 0 ? (
          <p className="muted">Noch keine Beobachtungen.</p>
        ) : (
          <>
            <div className="bar" aria-hidden="true">
              {counts.positive > 0 && (
                <span className="seg pos" style={{ flex: counts.positive }} />
              )}
              {counts.neutral > 0 && (
                <span className="seg neu" style={{ flex: counts.neutral }} />
              )}
              {counts.negative > 0 && (
                <span className="seg neg" style={{ flex: counts.negative }} />
              )}
            </div>
            <p className="trend-legend">
              <span className="chip pos">{counts.positive} positiv</span>
              <span className="chip neu">{counts.neutral} neutral</span>
              <span className="chip neg">{counts.negative} negativ</span>
              <span className="avg">Ø Note: {summary.avg_score ?? "—"}</span>
            </p>
          </>
        )}
      </div>

      {summary.timeline_truncated && (
        <p className="muted small">
          Es werden die neuesten Beobachtungen angezeigt. Der vollständige
          Verlauf ist im CSV- und PDF-Export enthalten.
        </p>
      )}

      {/* chronological list, newest first */}
      <ul className="obs-list">
        {[...summary.timeline].reverse().map((o) => (
          <li key={o.id} className={`obs-item status-sent-${o.sentiment}`}>
            <div className="obs-meta">
              <span className="muted">{fmtDate(o.lesson_date)}</span>
              <button className="del" onClick={() => remove(o.id)}>
                löschen
              </button>
            </div>
            <textarea
              key={`text-${o.id}-${o.text}`}
              defaultValue={o.text}
              rows={2}
              onBlur={(e) => {
                if (e.target.value !== o.text)
                  save(o.id, { text: e.target.value });
              }}
            />
            <div className="obs-controls">
              <select
                value={o.sentiment}
                onChange={(e) => save(o.id, { sentiment: e.target.value })}
              >
                {SENTIMENTS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
              <label className="score">
                Note
                <input
                  key={`score-${o.id}-${o.manual_score}`}
                  type="number"
                  min="1"
                  max="6"
                  step="0.5"
                  defaultValue={o.manual_score ?? ""}
                  onBlur={(e) => {
                    const v =
                      e.target.value === "" ? null : Number(e.target.value);
                    if (v !== o.manual_score) save(o.id, { manual_score: v });
                  }}
                />
              </label>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
