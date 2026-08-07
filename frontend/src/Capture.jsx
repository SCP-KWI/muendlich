import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { useDictation } from "./useDictation.js";

// The in-app mic is opt-in, not opt-out. The Web Speech API is only offered when
// the browser can recognize speech on-device (see useDictation.js) — otherwise
// the audio would be uploaded to a third party. The default path is the
// keyboard's own dictation, which the operating system handles and which works
// in every browser.
const VOICE_ON_KEY = "muendlich_voice_on";

function readVoicePreference() {
  try {
    return localStorage.getItem(VOICE_ON_KEY) === "1";
  } catch {
    return false;
  }
}

function writeVoicePreference(on) {
  try {
    localStorage.setItem(VOICE_ON_KEY, on ? "1" : "0");
  } catch {
    /* private mode — the preference just won't persist */
  }
}

export function Capture({ klass, onDraft }) {
  const { supported, listening, transcript, error, start, stop, setText } =
    useDictation("de-DE");
  const [text, setLocal] = useState("");
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState(null);
  const [voiceOn, setVoiceOn] = useState(readVoicePreference);
  const areaRef = useRef(null);

  const value = listening ? transcript : text;
  const showMic = supported && voiceOn;

  // Recognition failed or was blocked → back to keyboard mode, and focus the
  // field so the keyboard (with its mic) comes up right away.
  useEffect(() => {
    if (error) {
      setVoiceOn(false);
      writeVoicePreference(false);
      setLocal((prev) => transcript || prev);
      areaRef.current?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  function enableVoice() {
    setVoiceOn(true);
    writeVoicePreference(true);
  }

  function disableVoice() {
    if (listening) stop();
    setLocal(transcript || text);
    setVoiceOn(false);
    writeVoicePreference(false);
  }

  function toggleMic() {
    if (listening) {
      stop();
      setLocal(transcript);
    } else {
      setText(text); // seed recognizer with any existing text
      start();
    }
  }

  function onEdit(e) {
    setLocal(e.target.value);
    setText(e.target.value);
  }

  async function send() {
    const raw = (listening ? transcript : text).trim();
    if (!raw) return;
    if (listening) stop();
    setBusy(true);
    setSendError(null);
    try {
      const draft = await api.createCapture(klass.id, raw);
      onDraft(draft);
    } catch (err) {
      setSendError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>{klass.name}</h2>

      {showMic && (
        <>
          <button
            className={listening ? "mic mic-on" : "mic"}
            onClick={toggleMic}
            aria-label={listening ? "Aufnahme stoppen" : "Diktat starten"}
          >
            <span className="mi">{listening ? "stop_circle" : "mic"}</span>
            {listening ? "Stoppen" : "Diktieren"}
          </button>
          <button className="link" onClick={disableVoice}>
            In-App-Mikrofon ausschalten
          </button>
        </>
      )}

      <textarea
        ref={areaRef}
        className="transcript"
        placeholder="Anna war heute super, hat Beatrice geholfen. Colin ging mir auf die Nerven."
        value={value}
        onChange={onEdit}
        rows={6}
      />

      <p className="muted hint">
        <span className="mi">keyboard_voice</span>
        <span>
          Für Spracheingabe ins Feld tippen und das Mikrofon-Symbol der Tastatur
          verwenden — das funktioniert in jedem Browser und die Verarbeitung
          übernimmt das Betriebssystem.
        </span>
      </p>

      {supported && !voiceOn && (
        <p className="muted hint small">
          <button className="link" onClick={enableVoice}>
            In-App-Diktat aktivieren
          </button>{" "}
          — dieser Browser erkennt Sprache lokal auf dem Gerät.
        </p>
      )}

      {sendError && <p className="error">{sendError}</p>}

      <button
        className="primary"
        onClick={send}
        disabled={busy || !value.trim()}
      >
        {busy ? "Verarbeite…" : "Auswerten"}
      </button>
    </div>
  );
}
