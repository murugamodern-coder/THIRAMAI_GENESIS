import { memo, useCallback, useRef, useState } from "react";

function readToken() {
  try {
    return (
      (localStorage.getItem("thiramai_jwt") || sessionStorage.getItem("thiramai_jwt") || "").trim()
    );
  } catch {
    return "";
  }
}

function VoiceButton() {
  const [status, setStatus] = useState("");
  const [listening, setListening] = useState(false);
  const recRef = useRef(null);

  const stop = useCallback(() => {
    try {
      recRef.current && recRef.current.stop();
    } catch {
      /* ignore */
    }
    recRef.current = null;
    setListening(false);
  }, []);

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setStatus("Speech recognition not supported in this browser.");
      return;
    }
    const t = readToken();
    if (!t) {
      setStatus("JWT required.");
      return;
    }

    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    recRef.current = rec;
    setListening(true);
    setStatus("Listening…");

    rec.onresult = (ev) => {
      const text = (ev.results && ev.results[0] && ev.results[0][0] && ev.results[0][0].transcript) || "";
      const phrase = String(text).trim();
      stop();
      if (!phrase) {
        setStatus("No speech captured.");
        return;
      }
      setStatus("Sending…");
      fetch(`${window.location.origin}/personal/quick-intent`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${t}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ phrase }),
      })
        .then((r) =>
          r.json().then((j) => ({
            ok: r.ok,
            j,
          })),
        )
        .then((x) => {
          if (x.ok) {
            setStatus(`OK: ${phrase.slice(0, 80)}`);
            window.dispatchEvent(new CustomEvent("cc-request-refresh"));
          } else {
            const d = x.j && x.j.detail;
            setStatus(typeof d === "string" ? d : JSON.stringify(d || x.j).slice(0, 200));
          }
        })
        .catch(() => setStatus("Network error"));
    };

    rec.onerror = () => {
      stop();
      setStatus("Mic error — try again.");
    };

    rec.onend = () => {
      setListening(false);
    };

    try {
      rec.start();
    } catch {
      stop();
      setStatus("Could not start microphone.");
    }
  }, [stop]);

  const onClick = useCallback(() => {
    if (listening) {
      stop();
      setStatus("Stopped.");
      return;
    }
    start();
  }, [listening, start, stop]);

  return (
    <div className="cc-voice-wrap">
      <button
        type="button"
        className={`cc-mic-btn${listening ? " cc-mic-btn--on" : ""}`}
        onClick={onClick}
        title={listening ? "Stop" : "Voice command"}
        aria-label={listening ? "Stop voice capture" : "Start voice command"}
      >
        <svg className="cc-mic-icon-svg" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 14a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v4a3 3 0 0 0 3 3zm5-3a5 5 0 1 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"
          />
        </svg>
      </button>
      {status ? (
        <p className="cc-voice-status" role="status">
          {status}
        </p>
      ) : null}
    </div>
  );
}

export default memo(VoiceButton);
