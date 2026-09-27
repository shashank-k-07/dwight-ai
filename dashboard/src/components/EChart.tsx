"use client";
// Thin ECharts wrapper: tree-shaken modules, SVG renderer, resizes with its box.
// Pass `option`; `onClick` gets ECharts' click params (params.data is your data item).
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, SunburstChart, TreemapChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([BarChart, SunburstChart, TreemapChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

export type ChartClick = { data?: unknown; name?: string; seriesName?: string; dataIndex?: number };

export function EChart({ option, height, onClick, ariaLabel }: {
  option: EChartsCoreOption;
  height: number;
  onClick?: (p: ChartClick) => void;
  ariaLabel: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onClick);
  click.current = onClick;

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, null, { renderer: "svg" });
    chart.current = c;
    c.on("click", (p) => click.current?.(p as ChartClick));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={el} role="img" aria-label={ariaLabel} style={{ width: "100%", height }} />;
}
