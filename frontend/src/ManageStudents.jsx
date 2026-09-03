import { useEffect, useState } from "react";
import { api } from "./api.js";
import { ConfirmDialog } from "./ConfirmDialog.jsx";
import { ErrorBanner, Notice } from "./ErrorBanner.jsx";
import { StudentListInput, describeBatchResult } from "./StudentListInput.jsx";

const NAME_REQUIRED = "Bitte geben Sie einen Namen ein.";

export function ManageStudents({ klass, onBack }) {
  const [students, setStudents] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [name, setName] = useState("");
  const [shortName, setShortName] = useState("");
  const [aliases, setAliases] = useState("");
  // A second tap on the submit button — trivially easy on a touchscreen — used
  // to fire a second POST and add the student twice.
  const [busy, setBusy] = useState(false);
  // An empty name field used to abort the submit silently; the browser's red
  // outline was the only hint, and screen readers got nothing at all.
  const [nameError, setNameError] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  // The pasted class list: names as parsed by StudentListInput, and a key that
  // remounts (clears) it once they are saved.
  const [batchNames, setBatchNames] = useState([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchKey, setBatchKey] = useState(0);

  function load() {
    api
      .listStudents(klass.id)
      .then(setStudents)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [klass.id]);

  async function addMany(e) {
    e.preventDefault();
    if (!batchNames.length || batchBusy) return;
    setError(null);
    setNotice(null);
    setBatchBusy(true);
    try {
      const res = await api.createStudents(
        klass.id,
        batchNames.map((n) => ({ full_name: n }))
      );
      setNotice(describeBatchResult(res));
      setBatchKey((k) => k + 1);
      setBatchNames([]);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBatchBusy(false);
    }
  }

  async function add(e) {
    e.preventDefault();
    if (!name.trim()) {
      setNameError(NAME_REQUIRED);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api.createStudent(klass.id, {
        full_name: name.trim(),
        short_name: shortName.trim() || null,
        aliases: aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      setName("");
      setShortName("");
      setAliases("");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveStudent(id, patch) {
    try {
      await api.updateStudent(id, patch);
      load();
    } catch (e) {
      setError(e.message);
    }
  }
  async function removeStudent(s) {
    setPendingDelete(null);
    try {
      await api.deleteStudent(s.id);
      load();
    } catch (e) {
      setError(e.message);
    }
  }
  async function addAlias(studentId, value) {
    if (!value.trim()) return;
    try {
      await api.addAlias(studentId, value.trim());
      load();
    } catch (e) {
      setError(e.message);
    }
  }
  async function removeAlias(id) {
    try {
      await api.deleteAlias(id);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  // Only bail out when the initial load failed and there is nothing to show —
  // still with the back button, or the teacher is stuck on a blank screen.
  if (error && students === null)
    return (
      <div>
        <button className="link back" onClick={onBack}>
          ← Klassen
        </button>
        <ErrorBanner message={error} />
      </div>
    );
  if (students === null) return <p className="muted">Lade…</p>;

  return (
    <div>
      <button className="link back" onClick={onBack}>
        ← Klassen
      </button>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <Notice message={notice} onDismiss={() => setNotice(null)} />
      <h2>{klass.name} · Schüler/innen</h2>

      <ul className="manage-list">
        {students.map((s) => (
          <li
            key={s.id}
            className={s.active ? "manage-item" : "manage-item inactive"}
          >
            <div className="student-edit">
              <input
                className="stud-name"
                defaultValue={s.full_name}
                onBlur={(e) =>
                  e.target.value.trim() &&
                  e.target.value !== s.full_name &&
                  saveStudent(s.id, { full_name: e.target.value.trim() })
                }
              />
              <input
                className="stud-short"
                placeholder="Rufname"
                defaultValue={s.short_name ?? ""}
                onBlur={(e) =>
                  (e.target.value.trim() || null) !== s.short_name &&
                  saveStudent(s.id, {
                    short_name: e.target.value.trim() || null,
                  })
                }
              />
            </div>

            <div className="alias-row">
              {s.aliases.map((a) => (
                <span key={a.id} className="alias-chip">
                  {a.alias}
                  <button
                    className="alias-x"
                    onClick={() => removeAlias(a.id)}
                    aria-label="Alias entfernen"
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                className="alias-add"
                placeholder="+ Alias"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addAlias(s.id, e.target.value);
                    e.target.value = "";
                  }
                }}
              />
            </div>

            <div className="manage-actions">
              <button
                className="link"
                onClick={() => saveStudent(s.id, { active: !s.active })}
              >
                {s.active ? "deaktivieren" : "aktivieren"}
              </button>
              <button className="del" onClick={() => setPendingDelete(s)}>
                löschen
              </button>
            </div>
          </li>
        ))}
      </ul>

      {/* The whole list first: at the start of a semester that is how a class
          gets filled. The one-at-a-time form below stays for latecomers. */}
      <form className="card add-form batch-form" onSubmit={addMany} noValidate>
        <h3>Klassenliste einfügen</h3>
        <StudentListInput
          key={batchKey}
          idPrefix="roster-list"
          onChange={setBatchNames}
          disabled={batchBusy}
        />
        <button
          className="primary"
          type="submit"
          disabled={batchBusy || batchNames.length === 0}
        >
          {batchBusy
            ? "…"
            : batchNames.length
              ? `${batchNames.length} hinzufügen`
              : "Hinzufügen"}
        </button>
      </form>

      {/* noValidate, but the input keeps `required` — see ManageClasses.jsx. */}
      <form className="card add-form single-form" onSubmit={add} noValidate>
        <h3>Einzelne Person hinzufügen</h3>
        <input
          id="new-student-name"
          className={nameError ? "invalid" : undefined}
          placeholder="Voller Name"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            if (e.target.value.trim()) setNameError(null);
          }}
          required
          aria-invalid={!!nameError}
          aria-describedby={nameError ? "new-student-name-error" : undefined}
        />
        {nameError && (
          <p className="field-error" id="new-student-name-error">
            {nameError}
          </p>
        )}
        <div className="row">
          <input
            placeholder="Rufname (optional)"
            value={shortName}
            onChange={(e) => setShortName(e.target.value)}
          />
          <input
            placeholder="Aliasse, kommagetrennt"
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
          />
        </div>
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "…" : "Hinzufügen"}
        </button>
      </form>

      {pendingDelete && (
        <ConfirmDialog
          title="Schüler/in löschen?"
          message={`„${pendingDelete.full_name}“ löschen? Beobachtungen bleiben erhalten.`}
          onConfirm={() => removeStudent(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
