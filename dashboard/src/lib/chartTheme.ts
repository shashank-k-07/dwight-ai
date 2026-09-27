"use client";
// Chart colours and ECharts theme. Business Function colours are a fixed map (colour follows
// the entity, never its rank), validated with the dataviz skill's validate_palette.js on the
// adjacent pairlist in both modes: light worst CVD ΔE 11.4 / normal 24.6; dark 11.3 / 24.6.
// Gold sits below 3:1 on the light surface, so every chart that uses it is direct-labelled and
// has a table view. Waste coral vs Spend indigo: CVD ΔE 21.4 light / 20.6 dark.
import { useEffect, useState } from "react";

const BF_ORDER = ["Engineering", "Marketing", "Operations", "Customer Experience", "Finance"] as const;
const LIGHT = { bf: ["#3e63dd", "#e2702a", "#29a383", "#ab4aba", "#d4952a"], other: "#8b8d98", spend: "#3e63dd", waste: "#f0616d" };
const DARK = { bf: ["#5b7cf0", "#e2702a", "#29a383", "#b65bc4", "#b88016"], other: "#8b8d98", spend: "#5b7cf0", waste: "#e5505d" };

export interface ChartColors {
  dark: boolean;
  bf: (name: string | null | undefined) => string;
  spend: string;
  waste: string;
  text: string;
  textMuted: string;
  grid: string;
  surface: string;
}

function read(dark: boolean): ChartColors {
  const p = dark ? DARK : LIGHT;
  const css = typeof window === "undefined" ? null : getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback;
  return {
    dark,
    bf: (name) => {
      const i = BF_ORDER.indexOf((name ?? "") as (typeof BF_ORDER)[number]);
      return i >= 0 ? p.bf[i] : p.other; // a 6th Business Function folds to neutral, never a generated hue
    },
    spend: p.spend,
    waste: p.waste,
    text: v("--text-primary", dark ? "#fff" : "#0b0b0b"),
    textMuted: v("--text-muted", "#77766f"),
    grid: v("--grid", dark ? "#2a2a27" : "#ecebe7"),
    surface: v("--surface", dark ? "#1a1a19" : "#fcfcfb"),
  };
}

/** Colours for the current color scheme; re-renders when the OS theme flips. */
export function useChartColors(): ChartColors {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setDark(mq.matches && document.documentElement.dataset.theme !== "light");
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return read(dark);
}

/** Tint a hex toward the surface: used for a Team inside its Business Function's hue. */
export function tint(hex: string, amount: number, surface = "#ffffff"): string {
  const h = (s: string) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16));
  const [a, b] = [h(hex), h(surface.startsWith("#") && surface.length === 7 ? surface : "#ffffff")];
  return "#" + a.map((c, i) => Math.round(c + (b[i] - c) * amount).toString(16).padStart(2, "0")).join("");
}

/** Shared tooltip look. */
export function tooltipStyle(c: ChartColors) {
  return {
    backgroundColor: c.surface,
    borderColor: c.grid,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: c.text, fontSize: 12 },
    extraCssText: "border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,.12);",
  };
}

/** A shade of one hue for t in [0, 1]: 0 = light (tinted toward the surface), 1 = deep (toward black). */
export function shade(hex: string, t: number, surface: string): string {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? tint(hex, 0.55 * (1 - x / 0.5), surface) : tint(hex, 0.4 * ((x - 0.5) / 0.5), "#000000");
}

/** White ink on dark fills, near-black on light ones. */
export function inkOn(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 ? "#10233f" : "#ffffff";
}
