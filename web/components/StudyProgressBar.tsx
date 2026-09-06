"use client";

type StudyProgressBarProps = {
  completed: number;
  total: number;
  streak: number;
  estimatedMinsLeft: number;
};

export function StudyProgressBar({
  completed,
  total,
  streak,
  estimatedMinsLeft,
}: StudyProgressBarProps) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const goalMet = completed >= total && total > 0;

  return (
    <div className="study-progress-bar">
      <div className="flex flex-wrap items-center gap-4 md:gap-6">
        <ProgressRing pct={pct} completed={completed} total={total} goalMet={goalMet} />

        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-100">
            {goalMet ? "Today’s goal complete" : "Today’s study goal"}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            {completed}/{total} stories done · ~{estimatedMinsLeft} min left
          </p>
          <div className="study-progress-track mt-3">
            <div
              className="study-progress-fill"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {streak > 0 ? (
          <div className="study-streak-badge" title="Consecutive study days">
            <span aria-hidden>🔥</span>
            <div>
              <p className="text-lg font-bold leading-none text-saffron">{streak}</p>
              <p className="text-[9px] uppercase tracking-wider text-slate-500">day streak</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ProgressRing({
  pct,
  completed,
  total,
  goalMet,
}: {
  pct: number;
  completed: number;
  total: number;
  goalMet: boolean;
}) {
  const r = 28;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;

  return (
    <div className="relative flex h-[72px] w-[72px] shrink-0 items-center justify-center">
      <svg className="-rotate-90" width="72" height="72" aria-hidden>
        <circle cx="36" cy="36" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke={goalMet ? "#3BB8B0" : "#D4A054"}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-lg font-bold text-white">{completed}</span>
        <span className="text-[9px] text-slate-500">/ {total}</span>
      </div>
    </div>
  );
}
