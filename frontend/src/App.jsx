import { useEffect, useState } from "react";
import { api, isLoggedIn, restoreSession, setToken } from "./api.js";
import { Login } from "./Login.jsx";
import { ClassList } from "./ClassList.jsx";
import { Capture } from "./Capture.jsx";
import { DraftReview } from "./DraftReview.jsx";
import { Review } from "./Review.jsx";
import { Manage } from "./Manage.jsx";
import { HelpButton } from "./HelpButton.jsx";

export function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [checking, setChecking] = useState(true);
  const [section, setSection] = useState("capture"); // "capture" | "review" | "manage"

  // light/dark theme (persisted; initial value applied by the inline script in index.html)
  const [dark, setDark] = useState(
    () => document.documentElement.getAttribute("data-theme") === "dark"
  );
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    if (next) document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
    try {
      localStorage.setItem("chalk-theme", next ? "dark" : "light");
    } catch (e) {}
  }

  // capture-flow state
  const [view, setView] = useState("classes");
  const [klass, setKlass] = useState(null);
  const [draft, setDraft] = useState(null);
  const [result, setResult] = useState(null);

  // On load, try to restore the session from the refresh cookie.
  useEffect(() => {
    restoreSession()
      .then((ok) => setAuthed(ok))
      .finally(() => setChecking(false));
  }, []);

  function resetCapture() {
    setKlass(null);
    setDraft(null);
    setResult(null);
    setView("classes");
  }

  function logout() {
    api.logout().catch(() => {}); // clear the refresh cookie server-side
    setToken(null);
    setAuthed(false);
    resetCapture();
    setSection("capture");
  }

  if (checking) {
    return (
      <main>
        <p className="muted">Lade…</p>
      </main>
    );
  }

  if (!authed) {
    return (
      <main>
        {/* The login screen has no topbar, so the handbook gets its own row —
            it has to be reachable before anyone can sign in. */}
        <div className="login-top">
          <HelpButton />
        </div>
        <Login onLoggedIn={() => setAuthed(true)} />
      </main>
    );
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brand-badge">
            <span className="mi">visibility</span>
          </span>
          <span className="brand-name">muendlich</span>
        </div>
        <div className="topbar-actions">
          <HelpButton />
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label="Hell / Dunkel umschalten"
          >
            <span className="mi">{dark ? "light_mode" : "dark_mode"}</span>
          </button>
          <button className="link" onClick={logout}>
            Abmelden
          </button>
        </div>
      </header>

      <nav className="tabs">
        <button
          className={section === "capture" ? "tab active" : "tab"}
          onClick={() => setSection("capture")}
        >
          <span className="mi">mic</span>
          Aufnehmen
        </button>
        <button
          className={section === "review" ? "tab active" : "tab"}
          onClick={() => setSection("review")}
        >
          <span className="mi">insights</span>
          Übersicht
        </button>
        <button
          className={section === "manage" ? "tab active" : "tab"}
          onClick={() => setSection("manage")}
        >
          <span className="mi">tune</span>
          Verwalten
        </button>
      </nav>

      {section === "capture" && (
        <>
          {view !== "classes" && (
            <button className="link back" onClick={resetCapture}>
              ← Klassen
            </button>
          )}

          {view === "classes" && (
            <ClassList
              onSelect={(c) => {
                setKlass(c);
                setView("capture");
              }}
            />
          )}

          {view === "capture" && klass && (
            <Capture
              klass={klass}
              onDraft={(d) => {
                setDraft(d);
                setView("review");
              }}
            />
          )}

          {view === "review" && klass && draft && (
            <DraftReview
              klass={klass}
              draft={draft}
              onDone={(r) => {
                setResult(r);
                setView("done");
              }}
            />
          )}

          {view === "done" && result && (
            <div className="card center">
              <p className="big-ok">✓</p>
              <p>
                {result.saved.length} Beobachtung
                {result.saved.length === 1 ? "" : "en"} gespeichert
                {result.created_student_ids.length > 0 &&
                  ` · ${result.created_student_ids.length} neue/r Schüler/in`}
                .
              </p>
              <button
                className="primary"
                onClick={() => {
                  setDraft(null);
                  setResult(null);
                  setView("capture");
                }}
              >
                Neue Aufnahme
              </button>
              <button className="link" onClick={resetCapture}>
                Zu den Klassen
              </button>
            </div>
          )}
        </>
      )}

      {section === "review" && <Review />}

      {section === "manage" && <Manage />}
    </main>
  );
}
