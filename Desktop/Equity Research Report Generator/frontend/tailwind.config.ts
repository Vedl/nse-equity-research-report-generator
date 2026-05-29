import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class", // next-themes adds/removes "dark" class on <html>
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        // Fintech design tokens
        surface: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      // Tabular numbers for financial data
      fontVariantNumeric: {
        tabular: "tabular-nums",
      },
    },
  },
  plugins: [],
};
export default config;
