import { useState } from "react";
import { api, setToken } from "./api.js";

export function Login({ onLoggedIn, notice = null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Typing a shared demo password on a phone keyboard is error-prone, and the
  // login screen is the one place where nobody can be shoulder-surfing data
  // they don't already have.
  const [showPassword, setShowPassword] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { access_token } = await api.login(email, password);
      setToken(access_token);
      onLoggedIn();
    } catch (err) {
      setError(err.message || "Die Anmeldung ist fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h1>muendlich</h1>
      {/* Logged out, this screen was a name and two fields: someone opening a
          link from a colleague had no way to tell what the tool is. There is no
          self-registration, so this is an explanation, not a pitch. */}
      <p className="login-intro">
        Mündliche Beteiligung festhalten: Nach der Lektion kurz diktieren —
        muendlich teilt den Text in einzelne Beobachtungen auf, ordnet sie den
        Schüler/innen zu und sammelt sie über das Semester als Grundlage für die
        mündliche Note.{" "}
        <a href="/handbuch" target="_blank" rel="noopener">
          Zum Handbuch
        </a>
      </p>
      {notice && <p className="notice">{notice}</p>}
      <form onSubmit={submit}>
        <label>
          E-Mail
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Passwort
          {/* A <button> inside a <label> is safe: the label's activation
              behaviour is skipped for interactive descendants, so the toggle
              does not also re-focus the input. */}
          <span className="pw-field">
            <input
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              className="pw-toggle"
              onClick={() => setShowPassword((shown) => !shown)}
              aria-pressed={showPassword}
              aria-label={
                showPassword ? "Passwort verbergen" : "Passwort anzeigen"
              }
              title={showPassword ? "Passwort verbergen" : "Passwort anzeigen"}
            >
              <span className="mi">visibility</span>
            </button>
          </span>
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}
