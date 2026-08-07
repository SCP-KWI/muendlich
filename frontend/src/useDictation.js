import { useCallback, useEffect, useRef, useState } from "react";

// Speech-to-text via the Web Speech API.
//
// IMPORTANT — this is NOT on-device in general. In Chrome, webkitSpeechRecognition
// uploads the audio to Google's servers for recognition, so spoken pupil names
// leave the building. Chrome 139+ can be asked to keep recognition local via
// `processLocally`; where that is unavailable the mic is not offered at all.
// The keyboard's own dictation (see the hint in Capture.jsx) is handled by the
// operating system and is the default path.
const SpeechRecognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

// True only when the browser can recognize speech without sending audio away.
export function localRecognitionAvailable() {
  return (
    !!SpeechRecognition &&
    typeof SpeechRecognition.availableOnDevice === "function"
  );
}

export function useDictation(lang = "de-DE", { requireLocal = true } = {}) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const baseRef = useRef(""); // text accumulated from finalized results

  // Without on-device support, treat the feature as unsupported rather than
  // silently streaming audio to a third party.
  const supported = !!SpeechRecognition && (!requireLocal || localRecognitionAvailable());

  useEffect(() => {
    if (!supported) return;
    const recognition = new SpeechRecognition();
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    // Chrome 139+: refuse to fall back to server-side recognition.
    if (requireLocal && "processLocally" in recognition) {
      recognition.processLocally = true;
    }

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) baseRef.current += chunk + " ";
        else interim += chunk;
      }
      setTranscript((baseRef.current + interim).trimStart());
    };
    recognition.onerror = (e) => {
      setError(e.error || "dictation error");
      setListening(false);
    };
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    return () => {
      recognition.onresult = recognition.onerror = recognition.onend = null;
      try {
        recognition.stop();
      } catch {
        /* already stopped */
      }
    };
  }, [lang, supported, requireLocal]);

  const start = useCallback(() => {
    if (!supported) return;
    setError(null);
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch {
      /* start() throws if already running — ignore */
    }
  }, [supported]);

  const stop = useCallback(() => {
    if (!supported) return;
    try {
      recognitionRef.current.stop();
    } catch {
      /* already stopped */
    }
    setListening(false);
  }, [supported]);

  // Let the user (or the parent) edit / reset the text.
  const setText = useCallback((text) => {
    baseRef.current = text ? text + " " : "";
    setTranscript(text);
  }, []);

  return { supported, listening, transcript, error, start, stop, setText };
}
