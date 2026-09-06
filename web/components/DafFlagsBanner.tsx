import type { DAFFlag } from "@/lib/types";

export function DafFlagsBanner({ flags }: { flags: DAFFlag[] }) {
  if (!flags.length) return null;

  return (
    <div className="rounded-xl border border-red-500/30 bg-gradient-to-r from-red-500/10 to-red-500/5 p-4">
      <div className="flex items-center gap-2">
        <span className="text-base">⚠️</span>
        <h3 className="text-sm font-semibold text-red-200">DAF Consistency Alert</h3>
      </div>
      <ul className="mt-3 space-y-3">
        {flags.map((flag, i) => (
          <li key={i} className="rounded-lg bg-red-500/10 p-3 text-sm">
            <p className="text-red-100">{flag.message}</p>
            <p className="mt-1.5 text-xs text-red-300/70">
              You said: <span className="italic">&ldquo;{flag.candidate_said}&rdquo;</span>
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
