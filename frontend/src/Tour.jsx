// A short guided tour of the main screen: a dimmed page, a spotlight on one
// element at a time, and a card explaining it.
//
// Steps address their target with a `data-tour` attribute rather than a CSS
// class, so restyling a button can't silently break the tour. A step whose
// target isn't on screen still shows — centred, without a spotlight — rather
// than being skipped, because a missing target is usually a layout state (an
// empty class list) rather than a reason to say nothing.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const HOLE_PAD = 6; // breathing room around the highlighted element
const GAP = 12; // between the spotlight and the card
const EDGE = 12; // keep the card this far from the viewport edge
const MAX_WIDTH = 330;
const FALLBACK_CARD_HEIGHT = 170; // only used before the card has been measured

// Ends on the handbook, so the tour hands over to something more thorough than
// itself rather than being the only explanation a teacher ever gets.
export const TOUR_STEPS = [
  {
    target: '[data-tour="capture"]',
    title: "Aufnehmen",
    body: "Nach der Lektion: Klasse wählen, dann frei sprechen oder tippen. Die App zerlegt das in einzelne Beobachtungen — gespeichert wird erst, wenn Sie den Entwurf bestätigt haben.",
  },
  {
    target: '[data-tour="classes"]',
    title: "Ihre Klassen",
    body: "Hier wählen Sie die Klasse für die Aufnahme. Neue Klassen und Schüler/innen legen Sie unter «Verwalten» an.",
  },
  {
    target: '[data-tour="review"]',
    title: "Übersicht",
    body: "Alle Beobachtungen einer Klasse und jeder einzelnen Person — filtern, Noten ergänzen, als Beleg exportieren.",
  },
  {
    target: '[data-tour="manage"]',
    title: "Verwalten",
    body: "Klassen und Schüler/innen pflegen — eine ganze Klassenliste lässt sich auf einmal einfügen. Spitznamen sind hier besonders nützlich: Sie helfen der Zuordnung, wenn Sie beim Diktieren nur den Rufnamen sagen.",
  },
  {
    target: '[data-tour="handbook"]',
    title: "Handbuch",
    body: "Die ausführliche Anleitung mit Bildern — jederzeit über das «?» oben rechts erreichbar, auch bevor Sie angemeldet sind.",
    // The tour ends by handing over rather than just pointing: the button
    // behind the spotlight is not clickable while the overlay is up.
    link: { href: "/handbuch", label: "Handbuch öffnen" },
  },
];

function targetRect(selector) {
  const el = selector ? document.querySelector(selector) : null;
  if (!el) return null;
  const r = el.getBoundingClientRect();
  // A zero-sized box means the element is there but not laid out (hidden tab,
  // not yet rendered); treat that as "no target".
  if (r.width === 0 && r.height === 0) return null;
  return r;
}

export function Tour({ steps, onFinish }) {
  const [index, setIndex] = useState(0);
  const [hole, setHole] = useState(null);
  const [cardPos, setCardPos] = useState(null);
  const cardRef = useRef(null);

  const step = steps[index];
  const isLast = index === steps.length - 1;

  const measure = useCallback(() => {
    const r = targetRect(step?.target);
    setHole(
      r
        ? {
            top: r.top - HOLE_PAD,
            left: r.left - HOLE_PAD,
            width: r.width + HOLE_PAD * 2,
            height: r.height + HOLE_PAD * 2,
          }
        : null
    );
  }, [step]);

  // Bring the target into view before measuring, so a step further down the
  // page doesn't spotlight an off-screen rectangle.
  //
  // The deferred re-measures cover layout that settles after first paint — a
  // web font swapping in, an async list filling out — which moves a target
  // without necessarily changing the body's size, so the observer below would
  // not catch it.
  useEffect(() => {
    const el = step?.target ? document.querySelector(step.target) : null;
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
    measure();
    const timers = [setTimeout(measure, 0), setTimeout(measure, 300)];
    return () => timers.forEach(clearTimeout);
  }, [step, measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    // Capture phase: scrolling happens on inner containers too, not just window.
    window.addEventListener("scroll", measure, true);
    // The page also grows and shrinks under the tour — the demo banner arriving,
    // the class list finishing its fetch — which moves every target below it.
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      observer.disconnect();
    };
  }, [measure]);

  // Positioned after layout so the card's real height decides whether it goes
  // above or below the spotlight — one pass, before paint, so nothing jumps.
  useLayoutEffect(() => {
    const width = Math.min(MAX_WIDTH, window.innerWidth - EDGE * 2);
    const height = cardRef.current?.offsetHeight || FALLBACK_CARD_HEIGHT;

    if (!hole) {
      setCardPos({
        width,
        left: Math.max(EDGE, (window.innerWidth - width) / 2),
        top: Math.max(EDGE, (window.innerHeight - height) / 2),
      });
      return;
    }

    const below = hole.top + hole.height + GAP;
    const fitsBelow = below + height + EDGE <= window.innerHeight;
    const top = fitsBelow
      ? below
      : Math.max(EDGE, hole.top - GAP - height);

    const centred = hole.left + hole.width / 2 - width / 2;
    const left = Math.min(
      Math.max(EDGE, centred),
      window.innerWidth - width - EDGE
    );

    setCardPos({ top, left, width });
  }, [hole, index]);

  const finish = useCallback(() => onFinish(), [onFinish]);

  // Focus lands on the card each step, so a screen reader announces the new
  // content and keyboard users are already inside the dialog.
  //
  // Waits for cardPos: until the card has been positioned it is still
  // `visibility: hidden`, and a hidden element cannot take focus — so focusing
  // early silently does nothing and leaves the Tab trap with nothing to trap.
  // The ref keeps it to once per step, so it can't yank focus back off a button
  // every time a re-measure moves the card.
  const focusedStep = useRef(-1);
  useEffect(() => {
    if (cardPos && focusedStep.current !== index) {
      focusedStep.current = index;
      cardRef.current?.focus();
    }
  }, [index, cardPos]);

  function onKeyDown(e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      finish();
      return;
    }
    if (e.key !== "Tab") return;
    // Keep focus inside the dialog: everything behind it is inert anyway.
    const focusable = cardRef.current?.querySelectorAll("button, a[href]");
    if (!focusable?.length) return;
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

  if (!step) return null;

  return (
    <>
      {/* Swallows every click aimed at the app, so the screen can't change out
          from under a step that is pointing at it. */}
      <div className="tour-blocker" />
      {hole && (
        <div
          className="tour-hole"
          style={{
            top: hole.top,
            left: hole.left,
            width: hole.width,
            height: hole.height,
          }}
        />
      )}
      <div
        className="tour-card"
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        style={{
          ...cardPos,
          visibility: cardPos ? "visible" : "hidden",
        }}
      >
        <p className="tour-step">
          Schritt {index + 1} von {steps.length}
        </p>
        <h3 id="tour-title">{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-actions">
          <button className="link" type="button" onClick={finish}>
            {isLast ? "Schliessen" : "Überspringen"}
          </button>
          <span className="tour-spacer" />
          {step.link && (
            <a
              className="tour-link"
              href={step.link.href}
              target="_blank"
              rel="noopener"
            >
              {step.link.label}
            </a>
          )}
          {index > 0 && (
            <button
              className="link"
              type="button"
              onClick={() => setIndex((i) => i - 1)}
            >
              Zurück
            </button>
          )}
          <button
            className="tour-next"
            type="button"
            onClick={() => (isLast ? finish() : setIndex((i) => i + 1))}
          >
            {isLast ? "Fertig" : "Weiter"}
          </button>
        </div>
      </div>
    </>
  );
}
