import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        saffron: { DEFAULT: "#D4A054", light: "#E8C078", dark: "#B8863A", glow: "#D4A05440" },
        navy: { DEFAULT: "#111827", card: "#1a2332", border: "#2a3548", deep: "#0c1018" },
        india: { green: "#3BB8B0", white: "#F1F5F9" },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-jakarta)", "var(--font-inter)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 40px -8px rgba(212, 160, 84, 0.35)",
        "glow-lg": "0 0 60px -12px rgba(212, 160, 84, 0.45)",
        card: "0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)",
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        mesh: "radial-gradient(at 30% 10%, rgba(212,160,84,0.08) 0px, transparent 45%), radial-gradient(at 85% 15%, rgba(59,184,176,0.06) 0px, transparent 40%), radial-gradient(at 10% 60%, rgba(42,53,72,0.5) 0px, transparent 50%)",
      },
      animation: {
        "pulse-ring": "pulse-ring 1.5s cubic-bezier(0.4,0,0.6,1) infinite",
        float: "float 6s ease-in-out infinite",
        "float-delayed": "float 6s ease-in-out 2s infinite",
        shimmer: "shimmer 2.5s linear infinite",
        wave: "wave 1.2s ease-in-out infinite",
        "fade-up": "fade-up 0.6s ease-out forwards",
        "scale-in": "scale-in 0.4s ease-out forwards",
      },
      keyframes: {
        "pulse-ring": {
          "0%, 100%": { transform: "scale(1)", opacity: "0.5" },
          "50%": { transform: "scale(1.2)", opacity: "0" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-12px)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        wave: {
          "0%, 100%": { transform: "scaleY(0.4)" },
          "50%": { transform: "scaleY(1)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
