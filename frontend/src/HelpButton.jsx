// Opens the teacher handbook. nginx maps /handbuch to the bundled handbuch.html
// (vite.config.js does the same for the dev server); it needs no login, so this
// works on the login screen too.
//
// A plain "?" rather than an icon-font glyph: the Material Symbols font is
// subset to the icons the app already uses, and adding one would mean
// regenerating that subset for a single character.
//
// Deliberately not shown to pupils — this app has no pupil-facing screens, but
// its sister apps do, and there the handbook stays teacher-only.
export function HelpButton() {
  return (
    <a
      className="help-btn"
      data-tour="handbook"
      href="/handbuch"
      target="_blank"
      rel="noopener"
      title="Handbuch öffnen"
      aria-label="Handbuch öffnen"
    >
      ?
    </a>
  );
}
