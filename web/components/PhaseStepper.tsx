const PHASES = [
  { id: "daf_opening", label: "DAF Opening", short: "DAF", icon: "📋", desc: "Your background" },
  { id: "subject_probe", label: "Subject Probe", short: "Subject", icon: "📚", desc: "Optional depth" },
  { id: "current_affairs", label: "Current Affairs", short: "CA", icon: "📰", desc: "News + DAF link" },
  { id: "closing", label: "Closing", short: "Close", icon: "🎯", desc: "Motivation & ethics" },
];

export function PhaseStepper({ currentPhase }: { currentPhase: string }) {
  const idx = PHASES.findIndex((p) => p.id === currentPhase);
  const progress = idx >= 0 ? ((idx + 1) / PHASES.length) * 100 : 0;

  return (
    <div className="glass-card !p-4">
      {/* Progress bar */}
      <div className="mb-4 h-1 overflow-hidden rounded-full bg-navy-border">
        <div
          className="h-full rounded-full bg-gradient-to-r from-saffron via-saffron-light to-india-green transition-all duration-700"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="grid grid-cols-4 gap-2">
        {PHASES.map((p, i) => {
          const done = i < idx;
          const active = i === idx;
          return (
            <div
              key={p.id}
              className={`relative rounded-xl p-3 text-center transition-all duration-300 ${
                active
                  ? "bg-saffron/15 ring-1 ring-saffron/40"
                  : done
                    ? "bg-white/5"
                    : "opacity-40"
              }`}
            >
              <span className="text-lg">{p.icon}</span>
              <p className={`mt-1 text-xs font-semibold ${active ? "text-saffron" : "text-slate-300"}`}>
                {p.short}
              </p>
              <p className="mt-0.5 hidden text-[10px] text-slate-500 sm:block">{p.desc}</p>
              {done && (
                <span className="absolute right-2 top-2 text-[10px] text-emerald-400">✓</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
