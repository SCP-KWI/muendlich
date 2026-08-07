import { useState } from "react";
import { api, setToken } from "./api.js";

export function Login({ onLoggedIn, notice = null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { access_token } = await api.login(email, password);
      setToken(access_token);
      onLoggedIn();
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h1>muendlich</h1>
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
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}
