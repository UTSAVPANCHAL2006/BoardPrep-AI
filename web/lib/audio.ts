export type AudioPlaybackState = "idle" | "playing" | "paused";

let sharedAudio: HTMLAudioElement | null = null;
let sharedBase64: string | null = null;

export function sniffAudioMime(base64: string): string {
  try {
    const head = atob(base64.slice(0, 32));
    if (head.startsWith("RIFF")) return "audio/wav";
    if (head.startsWith("ID3")) return "audio/mpeg";
    const b0 = head.charCodeAt(0);
    const b1 = head.charCodeAt(1);
    if (b0 === 0xff && (b1 & 0xe0) === 0xe0) return "audio/mpeg";
    if (head.startsWith("OggS")) return "audio/ogg";
  } catch {
    /* fall through */
  }
  return "audio/wav";
}

export function createAudioFromBase64(base64: string): HTMLAudioElement {
  const mime = sniffAudioMime(base64);
  return new Audio(`data:${mime};base64,${base64}`);
}

/** Reuse the same Audio element when base64 is unchanged — avoids mid-playback resets. */
export function getStableAudio(base64: string): HTMLAudioElement {
  if (sharedBase64 === base64 && sharedAudio) {
    return sharedAudio;
  }
  if (sharedAudio) {
    sharedAudio.pause();
    sharedAudio.src = "";
  }
  sharedAudio = createAudioFromBase64(base64);
  sharedBase64 = base64;
  return sharedAudio;
}

export function releaseStableAudio(): void {
  if (sharedAudio) {
    sharedAudio.pause();
    sharedAudio.src = "";
    sharedAudio = null;
    sharedBase64 = null;
  }
}

export function formatAudioTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function pauseStableAudio(): void {
  if (sharedAudio && !sharedAudio.paused) {
    sharedAudio.pause();
  }
}

export function resumeStableAudio(): Promise<boolean> {
  if (!sharedAudio) return Promise.resolve(false);
  return sharedAudio.play().then(() => true).catch(() => false);
}

export function playStableAudioAndWait(base64: string): Promise<void> {
  return new Promise((resolve) => {
    if (!base64) {
      resolve();
      return;
    }
    const audio = getStableAudio(base64);
    const done = () => {
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
      resolve();
    };
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    if (audio.ended) {
      audio.currentTime = 0;
    }
    void audio.play().catch(done);
  });
}
