/** Phase 15: the one ECharts theme file (§5 engineering rule). ECharts needs literal hex, not CSS
 *  vars, so this is the single place the Phase 15 token palette (styles/tokens.css) is mirrored
 *  for chart use -- every chart option builder imports from here, never repeats a hex itself. */
export const chartTokens = {
  bg1: "#0d1219",
  bg2: "#131a24",
  bg3: "#1a2330",
  line1: "#1b2431",
  line2: "#263244",
  text1: "#e8eef5",
  text2: "#a5b1c0",
  text3: "#828ea0",
  accent: "#4c8dff",
  normal: "#2ea97d",
  suspect: "#e3b341",
  affected: "#f0883e",
  origin: "#ff5c57",
} as const;

export const fontSans = "'Inter Variable', system-ui, sans-serif";
export const fontMono = "'JetBrains Mono Variable', ui-monospace, monospace";

/** Shared option fragments every chart builder should spread in, so one tweak (a grid inset, a
 *  tooltip style) updates every chart at once. */
export const baseOption = {
  backgroundColor: "transparent",
  textStyle: { fontFamily: fontSans, color: chartTokens.text2 },
  animationDuration: 300,
  animationEasing: "cubicOut" as const,
};

export const axisLabelStyle = {
  color: chartTokens.text2,
  fontFamily: fontMono,
  fontSize: 11,
};

export const tooltipStyle = {
  backgroundColor: chartTokens.bg3,
  borderColor: chartTokens.line2,
  borderWidth: 1,
  textStyle: { color: chartTokens.text1, fontFamily: fontMono, fontSize: 12 },
};
