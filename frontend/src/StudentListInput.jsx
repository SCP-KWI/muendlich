import { useEffect, useMemo, useRef, useState } from "react";
import { parseNames, readNameFile } from "./nameList.js";

// Names typed, pasted, or read from a file, shown back as a preview before
// anything is sent. Used both while a class is being created and later on the
// class's own roster, so the parsing lives in nameList.js and only the
// presentation is here.
//
// Reports the parsed names upward through `onChange(names)` whenever they
// change; the parent decides when — and whether — to send them. To clear it
// after a successful send, remount it (change its `key`).

const PREVIEW_MAX = 60;

export function StudentListInput({ onChange, disabled = false, idPrefix = "student-list" }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState(null);
  const [fileError, setFileError] = useState(null);
  // Column choices the teacher made, overriding the guess in parseNames.
  const [cols, setCols] = useState({});
  const fileRef = useRef(null);

  const parsed = useMemo(() => parseNames(text, cols), [text, cols]);
  const names = parsed.names;
  // `names` is a fresh array only when text or column choice changed, so this
  // fires exactly then. onChange is deliberately not a dependency: parents
  // pass a state setter or an inline arrow, and neither should retrigger.
  useEffect(() => {
    onChange(names);
  }, [names]); // eslint-disable-line react-hooks/exhaustive-deps

  async function pickFile(e) {
    const file = e.target.files?.[0];
    // Reset, so choosing the same file again (after fixing it) fires again.
    e.target.value = "";
    if (!file) return;
    setFileError(null);
    try {
      const content = await readNameFile(file);
      setText(content);
      setFileName(file.name);
      setCols({});
    } catch (err) {
      setFileError(err.message);
    }
  }

  const textId = `${idPrefix}-text`;
  return (
    <div className="student-list-input">
      <label htmlFor={textId}>
        Namen einfügen – eine Person pro Zeile, oder eine ganze Tabelle mit
        einer Spalte «Vorname».
      </label>
      <textarea
        id={textId}
        rows={6}
        value={text}
        placeholder={"Anna\nBen\nColin …"}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          setFileName(null);
        }}
      />
      <div className="row file-row">
        <button
          type="button"
          className="file-btn"
          disabled={disabled}
          onClick={() => fileRef.current?.click()}
        >
          Datei wählen (CSV)
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.tsv,.txt,text/csv,text/plain,text/tab-separated-values"
          hidden
          onChange={pickFile}
        />
        {fileName && <span className="muted file-name">{fileName}</span>}
      </div>
      {fileError && <p className="field-error">{fileError}</p>}

      {parsed.kind === "table" && (
        <div className="row col-pick">
          <label>
            Vorname aus Spalte
            <select
              value={parsed.firstCol}
              disabled={disabled}
              onChange={(e) =>
                setCols((c) => ({ ...c, firstCol: Number(e.target.value) }))
              }
            >
              {parsed.columns.map((c, i) => (
                <option key={i} value={i}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Nachname aus Spalte
            <select
              value={parsed.lastCol}
              disabled={disabled}
              onChange={(e) =>
                setCols((c) => ({ ...c, lastCol: Number(e.target.value) }))
              }
            >
              <option value={-1}>– keine –</option>
              {parsed.columns.map((c, i) => (
                <option key={i} value={i}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {names.length > 0 && (
        <div className="name-preview" aria-live="polite">
          <span className="muted">
            {names.length === 1 ? "1 Person" : `${names.length} Personen`}:
          </span>
          {names.slice(0, PREVIEW_MAX).map((n, i) => (
            <span key={i} className="alias-chip">
              {n}
            </span>
          ))}
          {names.length > PREVIEW_MAX && (
            <span className="muted">… und {names.length - PREVIEW_MAX} weitere</span>
          )}
        </div>
      )}
      {parsed.warnings.map((w, i) => (
        <p key={i} className="field-warning">
          {w}
        </p>
      ))}
      <p className="muted privacy-hint">
        Eine Datei wird nur auf Ihrem Gerät gelesen; übertragen werden
        ausschliesslich die Namen.
      </p>
    </div>
  );
}

/** One line for the teacher about what a batch request did. */
export function describeBatchResult({ created, skipped }) {
  const n = created.length;
  const added =
    n === 0
      ? "Niemand hinzugefügt"
      : n === 1
        ? "1 Person hinzugefügt"
        : `${n} Personen hinzugefügt`;
  if (!skipped.length) return `${added}.`;
  return `${added}. Bereits in der Klasse (übersprungen): ${skipped.join(", ")}.`;
}
