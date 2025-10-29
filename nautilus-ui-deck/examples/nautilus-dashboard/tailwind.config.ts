import type { Config } from 'tailwindcss'

export default {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0D0E10",
          secondary: "#141519"
        },
        text: {
          primary: "#EAEAEA",
          secondary: "#9A9A9A"
        },
        accent: {
          hmm: "#00F5D4",
          meanrev: "#FFB400",
          breakout: "#FF3FB3"
        },
        success: "#00E676",
        alert: "#FF3B30",
        border: "rgba(255,255,255,0.05)"
      },
      borderRadius: {
        deck: "12px"
      },
      boxShadow: {
        soft: "0 2px 6px rgba(0,0,0,0.4)",
        elevated: "0 8px 20px rgba(0,0,0,0.6)"
      }
    }
  },
  plugins: []
} satisfies Config
