import { BarChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import type { BarRow } from "../../lib/metrics";
import { chartOption } from "./chartOption";

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export function MetricsChart({ rows }: { rows: readonly BarRow[] }) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={chartOption(rows)}
      style={{ height: "100%", width: "100%" }}
      opts={{ renderer: "canvas" }}
      notMerge
    />
  );
}
