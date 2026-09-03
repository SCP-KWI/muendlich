// A failed request used to replace the whole screen with a bare error line,
// which turned a rejected edit into a dead end: no nav back, no sight of the
// data. This shows the message above the still-intact screen instead, and can
// be dismissed once read.
//
// Screens still return early for errors that leave them with nothing to render
// (a failed initial load) — for those, pass `fatal` so the message is not
// dismissible.
export function ErrorBanner({ message, onDismiss = null }) {
  if (!message) return null;
  // No icon: the Material Symbols font is subset to the glyphs the app already
  // uses, and an error glyph is not among them.
  return (
    <div className="error-banner" role="alert">
      <span className="error-banner-text">{message}</span>
      {onDismiss && (
        <button
          type="button"
          className="error-banner-x"
          onClick={onDismiss}
          aria-label="Meldung schliessen"
        >
          ×
        </button>
      )}
    </div>
  );
}

// The counterpart for an outcome worth a sentence — "23 Personen hinzugefügt,
// 2 übersprungen" — where a silently refreshed list would leave the teacher
// counting.
export function Notice({ message, onDismiss = null }) {
  if (!message) return null;
  return (
    <div className="notice ok" role="status">
      <span className="error-banner-text">{message}</span>
      {onDismiss && (
        <button
          type="button"
          className="error-banner-x"
          onClick={onDismiss}
          aria-label="Meldung schliessen"
        >
          ×
        </button>
      )}
    </div>
  );
}
