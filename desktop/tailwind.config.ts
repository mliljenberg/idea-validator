import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#05070f",
          900: "#0b1021",
          800: "#121a31"
        },
        neon: {
          cyan: "#00d0ff",
          mint: "#2cffb2",
          rose: "#ff4f88",
          amber: "#ffb547"
        }
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(0, 208, 255, 0.35), 0 14px 48px rgba(0, 208, 255, 0.14)",
        panel: "0 24px 60px rgba(0, 0, 0, 0.45)"
      },
      animation: {
        pulseSoft: "pulseSoft 2.2s ease-in-out infinite",
        riseIn: "riseIn 260ms ease-out",
        blink: "blink 1s step-end infinite"
      },
      keyframes: {
        pulseSoft: {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" }
        },
        riseIn: {
          "0%": { transform: "translateY(6px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" }
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" }
        }
      }
    }
  },
  plugins: []
} satisfies Config;
