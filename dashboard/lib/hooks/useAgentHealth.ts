"use client";

import { useEffect, useState } from "react";
import { api } from "../api";
import { agentConfigured } from "../env";

export type AgentHealth =
  | { status: "unconfigured" }
  | { status: "checking" }
  | { status: "up"; warmed: { llm: boolean; tts: boolean; db: boolean } | null }
  | { status: "down"; error: string };

/** Polls GET /health so every page can say whether commands will work. */
export function useAgentHealth(intervalMs = 10000): AgentHealth {
  const [health, setHealth] = useState<AgentHealth>({ status: "checking" });
  useEffect(() => {
    if (!agentConfigured) return;
    let cancelled = false;
    const check = async () => {
      const res = await api.health();
      if (cancelled) return;
      if (res.ok) setHealth({ status: "up", warmed: res.data?.warmed ?? null });
      else setHealth({ status: "down", error: res.error });
    };
    const first = window.setTimeout(check, 0);
    const id = window.setInterval(check, intervalMs);
    window.addEventListener("focus", check);
    return () => {
      cancelled = true;
      window.clearTimeout(first);
      window.clearInterval(id);
      window.removeEventListener("focus", check);
    };
  }, [intervalMs]);
  return agentConfigured ? health : { status: "unconfigured" };
}
