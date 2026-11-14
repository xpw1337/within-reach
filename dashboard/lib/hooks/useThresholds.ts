"use client";

import { useEffect, useSyncExternalStore } from "react";
import { getThresholdState, loadThresholds, subscribeThresholds, type ThresholdState } from "../thresholds";

const SERVER: ThresholdState = { status: "loading", thresholds: null, error: null };

/** Shared /config/thresholds state. Retries every 15 s and on focus until it loads. */
export function useThresholds(): ThresholdState {
  const state = useSyncExternalStore(subscribeThresholds, getThresholdState, () => SERVER);
  useEffect(() => {
    void loadThresholds();
    const retry = () => {
      if (getThresholdState().status !== "ok") void loadThresholds();
    };
    window.addEventListener("focus", retry);
    const id = window.setInterval(retry, 15000);
    return () => {
      window.removeEventListener("focus", retry);
      window.clearInterval(id);
    };
  }, []);
  return state;
}
