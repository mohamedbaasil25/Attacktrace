import type { BarRow } from "../../lib/metrics";
import { axisLabelStyle, baseOption, chartTokens, tooltipStyle } from "./echartsTheme";

/** Grouped bars: baseline vs AttackTrace, one group per row. */
export function chartOption(rows: readonly BarRow[]) {
  return {
    ...baseOption,
    grid: { left: 36, right: 8, top: 32, bottom: 24 },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: chartTokens.text1 },
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
    },
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "shadow" as const },
      ...tooltipStyle,
      valueFormatter: (v: unknown) => (typeof v === "number" ? v.toFixed(2) : String(v)),
    },
    xAxis: {
      type: "category" as const,
      data: rows.map((r) => r.label),
      axisLine: { lineStyle: { color: chartTokens.line1 } },
      axisTick: { show: false },
      axisLabel: axisLabelStyle,
    },
    yAxis: {
      type: "value" as const,
      min: 0,
      max: 1,
      interval: 0.25,
      splitLine: { lineStyle: { color: chartTokens.line1 } },
      axisLabel: axisLabelStyle,
    },
    series: [
      {
        name: "Baseline",
        type: "bar" as const,
        data: rows.map((r) => r.baseline),
        itemStyle: { color: chartTokens.text3, borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 28,
      },
      {
        name: "AttackTrace",
        type: "bar" as const,
        data: rows.map((r) => r.attacktrace),
        itemStyle: { color: chartTokens.accent, borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 28,
      },
    ],
  };
}
