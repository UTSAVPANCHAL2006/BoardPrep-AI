/** Silence detection — auto-submit after a natural end-of-answer pause. */

export const VAD_DEFAULTS = {
  /** Wait this long after last speech before auto-submit (natural thinking gaps). */
  silenceMs: 7500,
  /** Require at least this much speech before silence can trigger submit. */
  minSpeechMs: 1000,
} as const;

export function attachSilenceAutoStop(
  stream: MediaStream,
  onSilence: () => void,
  options?: {
    silenceMs?: number;
    minSpeechMs?: number;
    onSpeechDetected?: () => void;
    onSilenceProgress?: (remainingMs: number) => void;
  }
): () => void {
  const silenceMs = options?.silenceMs ?? VAD_DEFAULTS.silenceMs;
  const minSpeechMs = options?.minSpeechMs ?? VAD_DEFAULTS.minSpeechMs;
  const onSpeechDetected = options?.onSpeechDetected;
  const onSilenceProgress = options?.onSilenceProgress;

  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);

  const samples = new Uint8Array(analyser.fftSize);
  let lastSpeechAt = 0;
  let speechStartedAt = 0;
  let speechStarted = false;
  let fired = false;

  const timer = window.setInterval(() => {
    if (fired) return;
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) {
      const v = (samples[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / samples.length);
    const now = Date.now();

    if (rms > 0.022) {
      if (!speechStarted) {
        speechStartedAt = now;
        onSpeechDetected?.();
      }
      speechStarted = true;
      lastSpeechAt = now;
      return;
    }

    if (speechStarted && now - speechStartedAt >= minSpeechMs) {
      const elapsed = now - lastSpeechAt;
      const remaining = silenceMs - elapsed;
      if (remaining > 0) {
        onSilenceProgress?.(remaining);
      }
    }

    if (
      speechStarted &&
      now - lastSpeechAt >= silenceMs &&
      now - speechStartedAt >= minSpeechMs
    ) {
      fired = true;
      cleanup();
      onSilence();
    }
  }, 120);

  function cleanup() {
    window.clearInterval(timer);
    source.disconnect();
    void ctx.close();
  }

  return cleanup;
}

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { resultIndex: number; results: { length: number; [i: number]: { isFinal: boolean; 0: { transcript: string } } } }) => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};

/** Browser live caption while mic is open (Chrome / Safari). */
export function startLiveCaption(onText: (text: string, isFinal: boolean) => void): () => void {
  if (typeof window === "undefined") return () => {};

  const W = window as Window & {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
  if (!SR) return () => {};

  const rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "hi-IN";
  rec.onresult = (event) => {
    let chunk = "";
    let isFinal = false;
    for (let i = event.resultIndex; i < event.results.length; i++) {
      chunk += event.results[i][0].transcript;
      if (event.results[i].isFinal) isFinal = true;
    }
    if (chunk.trim()) onText(chunk.trim(), isFinal);
  };
  rec.onerror = () => {};

  try {
    rec.start();
  } catch {
    return () => {};
  }

  return () => {
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
  };
}
