import { useEffect, useRef } from "react";

// Replaces window.confirm() for destructive actions. The native dialog worked,
// but it is unstyled, unbrandable, and rendered outside the page — a jarring
// last line of defence before a class's whole observation history goes away.
//
// Deliberately kept as a controlled component rather than a promise-returning
// helper: the caller already holds the item pending deletion in state, and the
// label usually needs that item's name in it.
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Löschen",
  cancelLabel = "Abbrechen",
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null);
  const dialogRef = useRef(null);

  // Escape cancels, as in the native dialog. Bound on the document because the
  // focused element may be either button.
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
        return;
      }
      // Minimal focus trap: only two buttons, so Tab just cycles between them.
      if (e.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll("button");
        if (!focusable || focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [onCancel]);

  // Focus the confirming button, not the cancelling one: a keyboard user who
  // opened this on purpose should not have to tab to finish the job. Escape and
  // the backdrop are both one keystroke/click away.
  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <div
        ref={dialogRef}
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-message"
        // The backdrop closes on click; clicks inside the dialog must not
        // bubble up to it.
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h3 id="confirm-title">{title}</h3>
        <p id="confirm-message" className="modal-message">
          {message}
        </p>
        <div className="modal-actions">
          <button type="button" className="modal-cancel" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            className="modal-confirm"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
