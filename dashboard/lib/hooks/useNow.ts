"use client";

import { useEffect, useState } from "react";

/** Current time in ms, refreshed on an interval. Null until mounted, so render stays pure. */
export function useNow(intervalMs = 1000, enabled = true): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [intervalMs, enabled]);
  return now;
}
