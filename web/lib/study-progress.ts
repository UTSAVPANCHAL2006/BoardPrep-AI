const PROGRESS_KEY = "boardprep_ca_progress";
const STREAK_KEY = "boardprep_ca_streak";

export type DailyProgress = {
  editionDate: string;
  listened: number[];
  lastIndex: number | null;
};

export type StreakData = {
  count: number;
  lastDate: string;
};

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function loadRaw(): DailyProgress | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(PROGRESS_KEY);
    return raw ? (JSON.parse(raw) as DailyProgress) : null;
  } catch {
    return null;
  }
}

export function loadDailyProgress(editionDate: string): DailyProgress {
  const stored = loadRaw();
  if (!stored || stored.editionDate !== editionDate) {
    return { editionDate, listened: [], lastIndex: null };
  }
  return stored;
}

export function saveDailyProgress(progress: DailyProgress): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(progress));
}

export function markStoryListened(editionDate: string, index: number): DailyProgress {
  const current = loadDailyProgress(editionDate);
  const listened = current.listened.includes(index)
    ? current.listened
    : [...current.listened, index].sort((a, b) => a - b);
  const next: DailyProgress = { editionDate, listened, lastIndex: index };
  saveDailyProgress(next);
  touchStreak();
  return next;
}

function loadStreak(): StreakData {
  if (typeof window === "undefined") return { count: 0, lastDate: "" };
  try {
    const raw = localStorage.getItem(STREAK_KEY);
    return raw ? (JSON.parse(raw) as StreakData) : { count: 0, lastDate: "" };
  } catch {
    return { count: 0, lastDate: "" };
  }
}

function touchStreak(): StreakData {
  const today = todayKey();
  const prev = loadStreak();
  if (prev.lastDate === today) return prev;

  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayKey = yesterday.toISOString().slice(0, 10);

  const count = prev.lastDate === yesterdayKey ? prev.count + 1 : 1;
  const next = { count, lastDate: today };
  localStorage.setItem(STREAK_KEY, JSON.stringify(next));
  return next;
}

export function getStudyStreak(): number {
  return loadStreak().count;
}
