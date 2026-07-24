/** Dark-first theme. Chart colors follow the validated dataviz palette
 *  (categorical slots 1-3 pass all-pairs CVD checks on the dark surface). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#0d0d0d",
        surface: "#1a1a19",
        raised: "#222221",
        ink: "#ffffff",
        ink2: "#c3c2b7",
        muted: "#898781",
        grid: "#2c2c2a",
        edge: "rgba(255,255,255,0.10)",
        s1: "#3987e5",
        s2: "#d95926",
        s3: "#199e70",
        good: "#0ca30c",
        warn: "#fab219",
        crit: "#d03b3b",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
