// Formatting helpers for values that are not unit conversions (those live in
// lib/thresholds.ts). Every helper returns "--" for missing input.
import { EMPTY } from "./copy";

export function pct(frac: number | null | undefined, digits = 0): string {
  if (frac === null || frac === undefined || !Number.isFinite(frac)) return EMPTY;
  return `${(frac * 100).toFixed(digits)}%`;
}

export function int(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return EMPTY;
  return Math.round(n).toLocaleString("en-US");
}

export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return EMPTY;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function clock(ts: string | null | undefined): string {
  if (!ts) return EMPTY;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return EMPTY;
  return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(ts: string | null | undefined): string {
  if (!ts) return EMPTY;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return EMPTY;
  return d.toLocaleString("en-US", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Seconds between two timestamps, or null if either is missing. */
export function secondsBetween(from: string | null | undefined, to: string | null | undefined): number | null {
  if (!from || !to) return null;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return (b - a) / 1000;
}

export function seconds(s: number | null | undefined, digits = 1): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return EMPTY;
  return `${s.toFixed(digits)} s`;
}

/** "+12.4 s" style offset for timelines. */
export function offset(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return EMPTY;
  const sign = s < 0 ? "-" : "+";
  const abs = Math.abs(s);
  if (abs < 60) return `${sign}${abs.toFixed(1)} s`;
  const m = Math.floor(abs / 60);
  const r = Math.round(abs - m * 60);
  return `${sign}${m}:${r.toString().padStart(2, "0")}`;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return EMPTY;
  return s.replace(/_/g, " ");
}
