/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Phase 15 token set
        surface: {
          0: "var(--bg-0)",
          1: "var(--bg-1)",
          2: "var(--bg-2)",
          3: "var(--bg-3)",
        },
        line: {
          1: "var(--line-1)",
          2: "var(--line-2)",
        },
        ink: {
          1: "var(--text-1)",
          2: "var(--text-2)",
          3: "var(--text-3)",
        },
        focus: "var(--focus)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        info: "var(--info)",
        neutralStatus: "var(--neutral)",
        normal: "var(--normal)",
        suspect: "var(--suspect)",
        affected: "var(--affected)",
        origin: "var(--origin)",
      },
      fontFamily: {
        sans: ['"Inter Variable"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', "ui-monospace", "monospace"],
      },
      fontSize: {
        caption: "var(--text-caption)",
        label: "var(--text-label)",
        body: "var(--text-body)",
        title: "var(--text-title)",
        heading: "var(--text-heading)",
        value: "var(--text-value)",
        kpi: "var(--text-kpi)",
      },
      borderRadius: {
        DEFAULT: "8px",
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
      },
      spacing: {
        unit: "8px",
        1: "var(--space-1)",
        2: "var(--space-2)",
        3: "var(--space-3)",
        4: "var(--space-4)",
        5: "var(--space-5)",
        6: "var(--space-6)",
        8: "var(--space-8)",
        10: "var(--space-10)",
        14: "var(--space-14)",
      },
      transitionDuration: {
        fast: "var(--motion-fast)",
        base: "var(--motion-base)",
        slow: "var(--motion-slow)",
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
    },
  },
  plugins: [],
};
