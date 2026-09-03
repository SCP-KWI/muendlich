import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { ConfirmDialog } from "./ConfirmDialog.jsx";
import { ErrorBanner } from "./ErrorBanner.jsx";
import { StudentListInput } from "./StudentListInput.jsx";

const EMPTY = { name: "", subject: "", semester: "", school_year: "" };
const NAME_REQUIRED = "Bitte geben Sie einen Namen ein.";

export function ManageClasses({ onOpenClass }) {
  const [classes, setClasses] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // class id being edited
  // A second tap on the submit button — trivially easy on a touchscreen — used
  // to fire a second POST and create the class twice.
  const [busy, setBusy] = useState(false);
  // `busy` disables the button, but only from the *next* render: a fast double
  // tap lands both clicks before React commits that, and both POST. A ref flips
  // synchronously inside the handler, which is the only thing the second click
  // can see. (The backend's duplicate check below is the real safety net; this
  // stops the request being made at all.)
  const submitting = useRef(false);
  // Set when the backend reports an existing class of the same name, holding
  // the payload so confirming can re-send it verbatim.
  const [duplicate, setDuplicate] = useState(null);
  // An empty name field used to abort the submit silently; the browser's red
  // outline was the only hint, and screen readers got nothing at all.
  const [nameError, setNameError] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  // The class list given along with the new class, as parsed by
  // StudentListInput; the key remounts (clears) it once saved.
  const [names, setNames] = useState([]);
  const [listKey, setListKey] = useState(0);

  function load() {
    api
      .listClasses()
      .then(setClasses)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function submitClass(payload) {
    if (submitting.current) return;
    submitting.current = true;
    setError(null);
    setBusy(true);
    try {
      const created = await api.createClass(payload);
      setForm(EMPTY);
      setDuplicate(null);
      if (names.length) {
        // The class exists from here on whatever happens next, so a failed
        // roster upload must not read as "class not created". The names stay
        // in the field so the teacher can open the class and try again.
        try {
          const res = await api.createStudents(
            created.id,
            names.map((n) => ({ full_name: n }))
          );
          setListKey((k) => k + 1);
          setNames([]);
          // Straight to the roster, where the result is visible.
          onOpenClass({ ...created, student_count: res.created.length });
          return;
        } catch (err) {
          setError(
            `Die Klasse «${created.name}» wurde angelegt, aber die Namensliste konnte nicht gespeichert werden: ${err.message}`
          );
        }
      }
      load();
    } catch (err) {
      if (err.code === "duplicate_class_name") {
        // Not an error the teacher can act on by reading it — offer the choice.
        setDuplicate({ payload, message: err.message });
      } else {
        setError(err.message);
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function create(e) {
    e.preventDefault();
    if (!form.name.trim()) {
      setNameError(NAME_REQUIRED);
      return;
    }
    await submitClass({
      name: form.name.trim(),
      subject: form.subject.trim() || null,
      semester: form.semester.trim() || null,
      school_year: form.school_year.trim() || null,
    });
  }

  async function save(id, patch) {
    try {
      await api.updateClass(id, patch);
      setEditing(null);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function remove(c) {
    setPendingDelete(null);
    try {
      await api.deleteClass(c.id);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  // Only bail out when the initial load failed and there is nothing to show.
  if (error && classes === null) return <ErrorBanner message={error} />;
  if (classes === null) return <p className="muted">Lade…</p>;

  return (
    <div>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <h2>Klassen verwalten</h2>

      <ul className="manage-list">
        {classes.map((c) => (
          <li key={c.id} className="manage-item">
            {editing === c.id ? (
              <ClassEditor
                initial={c}
                onCancel={() => setEditing(null)}
                onSave={(patch) => save(c.id, patch)}
              />
            ) : (
              <div className="manage-row">
                <button
                  className="manage-open"
                  onClick={() => onOpenClass(c)}
                  title="Schüler/innen verwalten"
                >
                  <span className="manage-name">{c.name}</span>
                  {c.subject && <span className="muted"> · {c.subject}</span>}
                  {(c.semester || c.school_year) && (
                    <span className="muted">
                      {" "}
                      · {[c.semester, c.school_year].filter(Boolean).join(" ")}
                    </span>
                  )}
                </button>
                <div className="manage-actions">
                  <button className="link" onClick={() => setEditing(c.id)}>
                    bearbeiten
                  </button>
                  <button className="del" onClick={() => setPendingDelete(c)}>
                    löschen
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      {/* noValidate, but the inputs keep `required`: the attribute still
          carries the semantics for assistive tech, while the browser's own
          validation bubble stands aside for the inline message below the
          field — which stays on screen instead of vanishing on the next
          keystroke. */}
      <form className="card add-form" onSubmit={create} noValidate>
        <h3>Neue Klasse</h3>
        <input
          id="new-class-name"
          className={nameError ? "invalid" : undefined}
          placeholder="Name (z. B. 3a Deutsch)"
          value={form.name}
          onChange={(e) => {
            setForm({ ...form, name: e.target.value });
            if (e.target.value.trim()) setNameError(null);
          }}
          required
          aria-invalid={!!nameError}
          aria-describedby={nameError ? "new-class-name-error" : undefined}
        />
        {nameError && (
          <p className="field-error" id="new-class-name-error">
            {nameError}
          </p>
        )}
        <div className="row">
          <input
            placeholder="Fach"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
          />
          <input
            placeholder="Semester (z. B. HS2026)"
            value={form.semester}
            onChange={(e) => setForm({ ...form, semester: e.target.value })}
          />
        </div>
        <input
          placeholder="Schuljahr (z. B. 2026/27)"
          value={form.school_year}
          onChange={(e) => setForm({ ...form, school_year: e.target.value })}
        />
        <div className="class-roster">
          <h4>
            Schüler/innen{" "}
            <span className="muted">(optional – geht auch später)</span>
          </h4>
          <StudentListInput
            key={listKey}
            idPrefix="class-list"
            onChange={setNames}
            disabled={busy}
          />
        </div>
        <button className="primary" type="submit" disabled={busy}>
          {busy
            ? "…"
            : names.length
              ? `Klasse mit ${names.length} Schüler/innen anlegen`
              : "Klasse anlegen"}
        </button>
      </form>

      {pendingDelete && (
        <ConfirmDialog
          title="Klasse löschen?"
          message={`Klasse „${pendingDelete.name}“ und alle zugehörigen Beobachtungen löschen?`}
          onConfirm={() => remove(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {duplicate && (
        <ConfirmDialog
          title="Klasse doppelt anlegen?"
          message={duplicate.message}
          confirmLabel="Trotzdem anlegen"
          onConfirm={() =>
            submitClass({ ...duplicate.payload, allow_duplicate: true })
          }
          onCancel={() => setDuplicate(null)}
        />
      )}
    </div>
  );
}

function ClassEditor({ initial, onSave, onCancel }) {
  const [f, setF] = useState({
    name: initial.name || "",
    subject: initial.subject || "",
    semester: initial.semester || "",
    school_year: initial.school_year || "",
  });
  return (
    <div className="editor">
      <input
        value={f.name}
        onChange={(e) => setF({ ...f, name: e.target.value })}
      />
      <div className="row">
        <input
          placeholder="Fach"
          value={f.subject}
          onChange={(e) => setF({ ...f, subject: e.target.value })}
        />
        <input
          placeholder="Semester"
          value={f.semester}
          onChange={(e) => setF({ ...f, semester: e.target.value })}
        />
      </div>
      <input
        placeholder="Schuljahr"
        value={f.school_year}
        onChange={(e) => setF({ ...f, school_year: e.target.value })}
      />
      <div className="row">
        <button
          className="primary"
          onClick={() =>
            onSave({
              name: f.name.trim(),
              subject: f.subject.trim() || null,
              semester: f.semester.trim() || null,
              school_year: f.school_year.trim() || null,
            })
          }
        >
          Speichern
        </button>
        <button className="link" onClick={onCancel}>
          Abbrechen
        </button>
      </div>
    </div>
  );
}
