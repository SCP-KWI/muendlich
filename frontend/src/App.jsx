import { useCallback, useEffect, useState } from "react";
import {
  api,
  isLoggedIn,
  restoreSession,
  setSessionLostHandler,
  setToken,
} from "./api.js";
import { Login } from "./Login.jsx";
import { ClassList } from "./ClassList.jsx";
import { Capture } from "./Capture.jsx";
import { DraftReview } from "./DraftReview.jsx";
import { Review } from "./Review.jsx";
import { Manage } from "./Manage.jsx";
import { HelpButton } from "./HelpButton.jsx";
import { Tour, TOUR_STEPS } from "./Tour.jsx";

// Keyed by user id rather than a single flag: a demo visitor is a brand-new
// user every session, so they always get the tour, while a teacher sees it once
// per device. Storing it server-side would survive a device change, but it is
// not worth a migration and an endpoint for a five-card walkthrough.
const TOUR_SEEN_PREFIX = "muendlich-tour-seen";

function tourAlreadySeen(userId) {
  try {
    return localStorage.getItem(`${TOUR_SEEN_PREFIX}:${userId}`) === "1";
  } catch {
    return false; // private mode / storage disabled: show it, harmlessly again
  }
}

function rememberTourSeen(userId) {
  try {
    localStorage.setItem(`${TOUR_SEEN_PREFIX}:${userId}`, "1");
  } catch {
    /* nothing to do — the tour is skippable either way */
  }
}

export function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [checking, setChecking] = useState(true);
  const [section, setSection] = useState("capture"); // "capture" | "review" | "manage"
  // Shown on the login screen after an involuntary sign-out.
  const [notice, setNotice] = useState(null);
  // Demo sessions are time-boxed. Held as an absolute local deadline derived
  // once from the server's "seconds remaining", so a wrong device clock can't
  // skew the countdown.
  const [demoDeadline, setDemoDeadline] = useState(null);
  const [demoLeft, setDemoLeft] = useState(null);
  // The signed-in user, as /api/me reports them. Drives the demo banner and
  // whether the first-run tour has already been seen.
  const [me, setMe] = useState(null);
  const [tourOpen, setTourOpen] = useState(false);

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

  const resetCapture = useCallback(() => {
    setKlass(null);
    setDraft(null);
    setResult(null);
    setView("classes");
  }, []);

  // Back to the login screen. `message` explains an involuntary sign-out; a
  // deliberate one needs no explanation.
  const endSession = useCallback(
    (message = null) => {
      setToken(null);
      setAuthed(false);
      setDemoDeadline(null);
      setDemoLeft(null);
      setMe(null);
      setTourOpen(false);
      resetCapture();
      setSection("capture");
      setNotice(message);
    },
    [resetCapture]
  );

  function logout() {
    // Revokes the token family server-side; for a demo session it also discards
    // the session's data immediately instead of waiting for the sweeper.
    api.logout().catch(() => {});
    endSession();
  }

  // One place handles a session ending underneath us, rather than every screen
  // that happens to be making a request when it does.
  useEffect(() => {
    setSessionLostHandler(() =>
      endSession("Die Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.")
    );
    return () => setSessionLostHandler(null);
  }, [endSession]);

  useEffect(() => {
    if (!authed) return undefined;
    let cancelled = false;
    api
      .me()
      .then((m) => {
        if (cancelled) return;
        setMe(m);
        setDemoDeadline(
          m.demo ? Date.now() + m.demo_seconds_remaining * 1000 : null
        );
        // Seeded here rather than left to the countdown effect below, so the
        // banner renders in the same commit as everything else that depends on
        // it. Otherwise it drops in one commit later and pushes the whole page
        // down — under a tour that has already measured where things are.
        setDemoLeft(m.demo ? m.demo_seconds_remaining : null);
        // Every demo visitor is new here by construction; a teacher only on
        // their first sign-in from this device.
        setTourOpen(m.demo || !tourAlreadySeen(m.id));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [authed]);

  const finishTour = useCallback(() => {
    setTourOpen(false);
    // Demo users are deliberately not remembered: their id is gone in half an
    // hour, and the next visitor on this browser should see the tour too.
    if (me && !me.demo) rememberTourSeen(me.id);
  }, [me]);

  // Counts down the demo banner, and signs the visitor out when it reaches zero
  // rather than waiting for the next request to fail — an idle tab should not
  // sit on a dead session showing data that no longer exists.
  useEffect(() => {
    if (demoDeadline === null) {
      setDemoLeft(null);
      return undefined;
    }
    const tick = () => {
      const left = Math.max(0, Math.round((demoDeadline - Date.now()) / 1000));
      setDemoLeft(left);
      if (left === 0) {
        endSession(
          "Die Demo-Sitzung ist abgelaufen. Die Demo-Daten wurden gelöscht."
        );
      }
    };
    tick();
    const id = setInterval(tick, 15_000);
    return () => clearInterval(id);
  }, [demoDeadline, endSession]);

  // The app has exactly one route; /handbuch is served by nginx and never gets
  // here. Everything else used to land silently on the default screen, because
  // both the SPA fallback and the service worker's navigateFallback answer any
  // path with the app shell — a stale bookmark looked like it had worked. The
  // status code stays 200 (that is the fallback's doing and not fixable from
  // here), but the dead link at least says so.
  if (!["/", "/index.html"].includes(window.location.pathname)) {
    return (
      <main>
        <div className="login-top">
          <HelpButton />
        </div>
        <div className="card center">
          <h1>Seite nicht gefunden</h1>
          <p className="muted">
            Die Adresse <code>{window.location.pathname}</code> gibt es hier
            nicht.
          </p>
          <button className="primary" onClick={() => window.location.replace("/")}>
            Zur Startseite
          </button>
        </div>
      </main>
    );
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
        <Login
          notice={notice}
          onLoggedIn={() => {
            setNotice(null);
            setAuthed(true);
          }}
        />
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

      {demoLeft !== null && (
        <div className="demo-banner" role="status">
          <strong>Demo-Sitzung</strong> — noch{" "}
          {Math.max(1, Math.ceil(demoLeft / 60))} Minuten. Sie arbeiten auf einer
          eigenen Kopie mit Beispieldaten; sie wird am Ende gelöscht.
        </div>
      )}

      <nav className="tabs">
        <button
          data-tour="capture"
          className={section === "capture" ? "tab active" : "tab"}
          onClick={() => setSection("capture")}
        >
          <span className="mi">mic</span>
          Aufnehmen
        </button>
        <button
          data-tour="review"
          className={section === "review" ? "tab active" : "tab"}
          onClick={() => setSection("review")}
        >
          <span className="mi">insights</span>
          Übersicht
        </button>
        <button
          data-tour="manage"
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
            // Wrapper rather than a hook inside ClassList: it returns a
            // different root while loading, on error, and when empty, so this
            // is the only node the tour can rely on being there.
            <div data-tour="classes">
              <ClassList
                onSelect={(c) => {
                  setKlass(c);
                  setView("capture");
                }}
              />
            </div>
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

      {tourOpen && <Tour steps={TOUR_STEPS} onFinish={finishTour} />}
    </main>
  );
}
