"use client";

export function Waveform({ active }: { active: boolean }) {
  const bars = [0, 1, 2, 3, 4, 5, 6, 7];
  return (
    <div className="flex h-8 items-end justify-center gap-1">
      {bars.map((i) => (
        <div
          key={i}
          className={`w-1 rounded-full bg-saffron transition-all ${
            active ? "animate-wave" : "h-2 opacity-30"
          }`}
          style={{
            height: active ? undefined : "8px",
            animationDelay: active ? `${i * 0.1}s` : undefined,
            ...(active ? { height: `${12 + (i % 3) * 8}px` } : {}),
          }}
        />
      ))}
    </div>
  );
}
