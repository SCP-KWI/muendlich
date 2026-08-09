import { useCallback, useEffect, useState } from "react";
import { api, download, safeFilename } from "./api.js";
import { ConfirmDialog } from "./ConfirmDialog.jsx";
import { ErrorBanner } from "./ErrorBanner.jsx";

const SENTIMENTS = [
  ["positive", "positiv"],
  ["neutral", "neutral"],
  ["negative", "negativ"],
];

const SCORE_MESSAGE = "Nur ganze und halbe Noten von 1 bis 6 (z. B. 4.5).";

function fmtDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

// The backend only accepts whole and half steps from 1 to 6. Catching that here
// keeps a typo from turning into a 422 the teacher has to recover from.
// An empty field is valid: it clears the grade.
function scoreError(raw) {
  if (raw === "") return null;
  const v = Number(raw);
  if (!Number.isFinite(v) || v < 1 || v > 6 || (v * 2) % 1 !== 0)
    return SCORE_MESSAGE;
  return null;
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
  // Keyed by observation id — the timeline renders one Note field per row.
  const [scoreErrors, setScoreErrors] = useState({});
  const [pendingDelete, setPendingDelete] = useState(null);

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

  function setScoreError(id, message) {
    setScoreErrors((prev) => {
      const next = { ...prev };
      if (message) next[id] = message;
      else delete next[id];
      return next;
    });
  }

  async function remove(id) {
    setPendingDelete(null);
    setError(null);
    try {
      await api.deleteObservation(id);
      applyLocal((timeline) => timeline.filter((o) => o.id !== id));
    } catch (e) {
      setError(e.message);
      load();
    }
  }

  // A failed initial load leaves nothing to render, so the error has to be the
  // screen — but with a way out, or the teacher is stranded here.
  if (summary === null && error)
    return (
      <div>
        <ErrorBanner message={error} />
        <button className="link back" onClick={onBack}>
          ← {backLabel}
        </button>
      </div>
    );
  if (summary === null) return <p className="muted">Lade…</p>;

  const { counts } = summary;
  const total = counts.positive + counts.neutral + counts.negative;

  return (
    <div>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
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
              <button className="del" onClick={() => setPendingDelete(o)}>
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
                  className={scoreErrors[o.id] ? "invalid" : undefined}
                  defaultValue={o.manual_score ?? ""}
                  onBlur={(e) => {
                    const raw = e.target.value;
                    // A number input hands back an empty string for anything it
                    // cannot parse — "4,3" off a German keyboard, say — which
                    // would otherwise read as "clear the grade" and silently
                    // drop the one that was there.
                    const message = e.target.validity.badInput
                      ? SCORE_MESSAGE
                      : scoreError(raw);
                    setScoreError(o.id, message);
                    // Leave the rejected value in the field so it can be fixed
                    // rather than retyped from memory.
                    if (message) return;
                    const v = raw === "" ? null : Number(raw);
                    if (v !== o.manual_score) save(o.id, { manual_score: v });
                  }}
                />
              </label>
            </div>
            {scoreErrors[o.id] && (
              <p className="field-error">{scoreErrors[o.id]}</p>
            )}
          </li>
        ))}
      </ul>

      {pendingDelete && (
        <ConfirmDialog
          title="Beobachtung löschen?"
          message={`Die Beobachtung vom ${fmtDate(
            pendingDelete.lesson_date
          )} wird endgültig gelöscht.`}
          onConfirm={() => remove(pendingDelete.id)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
