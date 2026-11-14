"use client";

import { useCallback, useSyncExternalStore } from "react";

const EVENT = "wr-stored-flag";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** A per-viewer boolean preference in localStorage. Falls back to the default when storage is blocked. */
export function useStoredFlag(key: string, fallback: boolean): [boolean, (v: boolean) => void] {
  const raw = useSyncExternalStore(
    (cb) => {
      window.addEventListener(EVENT, cb);
      window.addEventListener("storage", cb);
      return () => {
        window.removeEventListener(EVENT, cb);
        window.removeEventListener("storage", cb);
      };
    },
    () => read(key),
    () => null,
  );
  const value = raw === null ? fallback : raw === "1";
  const set = useCallback(
    (v: boolean) => {
      try {
        window.localStorage.setItem(key, v ? "1" : "0");
      } catch {
        // storage blocked: the flag still flips for this event
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return [value, set];
}
