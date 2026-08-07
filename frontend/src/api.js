// The access token lives in memory only (not localStorage) — more XSS-resistant.
// Longevity comes from the httpOnly refresh cookie the backend sets: on 401 we
// silently call /api/auth/refresh to get a new access token and retry.
let accessToken = null;

export function getToken() {
  return accessToken;
}
export function setToken(token) {
  accessToken = token || null;
}
export function isLoggedIn() {
  return !!accessToken;
}

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
  }
}

// Concurrent 401s must share one refresh. The backend rotates the refresh token
// and revokes the presented one, so two parallel refreshes would look like token
// reuse and (correctly) get the whole family revoked — logging the user out.
let refreshInFlight = null;

// The access token is renewed silently, so a *rejected* renewal is the only
// signal that a session has really ended — an expired demo, a revoked token
// family, a changed password. Individual screens can't each handle that, so the
// app registers one handler and gets returned to the login screen.
let onSessionLost = null;

export function setSessionLostHandler(fn) {
  onSessionLost = fn || null;
}

async function tryRefresh() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch("/api/auth/refresh", { method: "POST" });
      if (!res.ok) {
        // Only a session we actually held counts as lost — a fresh visitor's
        // restoreSession() also lands here, and that is not an expiry.
        const hadSession = accessToken !== null;
        accessToken = null;
        if (hadSession && onSessionLost) onSessionLost();
        return false;
      }
      accessToken = (await res.json()).access_token;
      return true;
    } catch {
      accessToken = null;
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

// Attempt to restore a session on app load using the refresh cookie.
export async function restoreSession() {
  return tryRefresh();
}

async function request(method, path, body, _retried = false) {
  const headers = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 401 && !_retried && !path.startsWith("/api/auth/")) {
    if (await tryRefresh()) return request(method, path, body, true);
    throw new ApiError(401, "Session expired. Please log in again.");
  }
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = null;
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : null);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  login: (email, password) =>
    request("POST", "/api/auth/login", { email, password }),
  logout: () => request("POST", "/api/auth/logout"),
  me: () => request("GET", "/api/me"),

  listClasses: () => request("GET", "/api/classes"),
  listStudents: (classId) =>
    request("GET", `/api/classes/${classId}/students`),
  createCapture: (classId, rawText, lessonDate) =>
    request("POST", `/api/classes/${classId}/captures`, {
      raw_text: rawText,
      lesson_date: lessonDate ?? null,
    }),
  commitCapture: (captureId, items, lessonDate) =>
    request("POST", `/api/captures/${captureId}/commit`, {
      items,
      lesson_date: lessonDate ?? null,
    }),

  // review
  // Server-side aggregate: the overview needs three counts per pupil, not every
  // observation body for the whole school year.
  classStats: (classId) => request("GET", `/api/classes/${classId}/stats`),
  listObservations: (classId, filters = {}) => {
    const q = new URLSearchParams();
    if (filters.studentId) q.set("student_id", filters.studentId);
    if (filters.sentiment) q.set("sentiment", filters.sentiment);
    if (filters.from) q.set("from", filters.from);
    if (filters.to) q.set("to", filters.to);
    if (filters.limit) q.set("limit", filters.limit);
    if (filters.offset) q.set("offset", filters.offset);
    const qs = q.toString();
    return request(
      "GET",
      `/api/classes/${classId}/observations${qs ? "?" + qs : ""}`
    );
  },
  studentSummary: (studentId) =>
    request("GET", `/api/students/${studentId}/summary`),
  updateObservation: (id, patch) =>
    request("PATCH", `/api/observations/${id}`, patch),
  deleteObservation: (id) => request("DELETE", `/api/observations/${id}`),

  // management
  createClass: (body) => request("POST", "/api/classes", body),
  updateClass: (id, patch) => request("PATCH", `/api/classes/${id}`, patch),
  deleteClass: (id) => request("DELETE", `/api/classes/${id}`),
  createStudent: (classId, body) =>
    request("POST", `/api/classes/${classId}/students`, body),
  updateStudent: (id, patch) => request("PATCH", `/api/students/${id}`, patch),
  deleteStudent: (id) => request("DELETE", `/api/students/${id}`),
  addAlias: (studentId, alias) =>
    request("POST", `/api/students/${studentId}/aliases`, { alias }),
  deleteAlias: (id) => request("DELETE", `/api/aliases/${id}`),
};

// Fetch a file with auth and trigger a browser download. Retries once via the
// refresh cookie if the access token has expired.
export async function download(path, filename, _retried = false) {
  const res = await fetch(path, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (res.status === 401 && !_retried && (await tryRefresh())) {
    return download(path, filename, true);
  }
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // The server sends an RFC 6266 Content-Disposition; `download` only needs a
  // safe local fallback, so strip anything path-like or control-ish.
  a.download = safeFilename(filename);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function safeFilename(name) {
  const cleaned = String(name ?? "")
    // Path separators, control characters, and characters illegal in Windows
    // filenames. Dots, spaces and letters (incl. umlauts) are preserved, so
    // "3a Deutsch.csv" survives intact.
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1f\x7f/\\:*?"<>|]/g, "_")
    .replace(/^\.+/, "") // no leading dots -> no hidden files
    .trim()
    .slice(0, 100);
  return cleaned || "export";
}

export { ApiError };
