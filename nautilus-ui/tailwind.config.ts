import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0D0E10",
          secondary: "#141519",
          elevated: "#1C1E24",
        },
        text: {
          primary: "#EAEAEA",
          secondary: "#9A9A9A",
        },
        accent: {
          hmm: "#00F5D4",
          meanrev: "#FFB400",
          breakout: "#FF3FB3",
        },
        venue: {
          binance: "#00E676",
          ibkr: "#FFD166",
          bybit: "#FF7C00",
        },
        alert: "#FF3B30",
        success: "#00E676",
      },
      accentColor: {
        hmm: "#00F5D4",
        meanrev: "#FFB400",
        breakout: "#FF3FB3",
      },
      borderRadius: {
        xl: "12px",
      },
      boxShadow: {
        soft: "0 2px 6px rgba(0,0,0,0.4)",
        elevated: "0 8px 20px rgba(0,0,0,0.6)",
      },
      spacing: {
        xxs: "4px",
        xs: "8px",
        sm: "12px",
        md: "16px",
        lg: "24px",
        xl: "32px"
      },
      fontFamily: {
        display: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular"],
        body: ["Inter", "system-ui", "Segoe UI"],
      },
    },
  },
  plugins: [],
}
export default config
