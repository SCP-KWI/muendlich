import { useEffect, useState } from "react";
import { api } from "./api.js";

const EMPTY = { name: "", subject: "", semester: "", school_year: "" };

export function ManageClasses({ onOpenClass }) {
  const [classes, setClasses] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // class id being edited

  function load() {
    api
      .listClasses()
      .then(setClasses)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    try {
      await api.createClass({
        name: form.name.trim(),
        subject: form.subject.trim() || null,
        semester: form.semester.trim() || null,
        school_year: form.school_year.trim() || null,
      });
      setForm(EMPTY);
      load();
    } catch (e) {
      setError(e.message);
    }
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
    if (
      !confirm(
        `Klasse „${c.name}“ und alle zugehörigen Beobachtungen löschen?`
      )
    )
      return;
    try {
      await api.deleteClass(c.id);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (classes === null) return <p className="muted">Lade…</p>;

  return (
    <div>
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
                  <button className="del" onClick={() => remove(c)}>
                    löschen
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      <form className="card add-form" onSubmit={create}>
        <h3>Neue Klasse</h3>
        <input
          placeholder="Name (z. B. 3a Deutsch)"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
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
        <button className="primary" type="submit">
          Klasse anlegen
        </button>
      </form>
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
