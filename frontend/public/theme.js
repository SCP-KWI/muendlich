// Restore the saved theme before first paint (avoids a light→dark flash).
// Kept as a separate file rather than an inline <script> so the Content-Security
// -Policy can be a strict `script-src 'self'` with no 'unsafe-inline'.
try {
  if (localStorage.getItem("chalk-theme") === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  }
} catch (e) {
  /* private mode / storage disabled — fall back to the light theme */
}
