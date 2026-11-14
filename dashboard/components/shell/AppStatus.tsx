"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useAgentHealth, type AgentHealth } from "@/lib/hooks/useAgentHealth";
import { useRealtimeTable, type FeedStatus } from "@/lib/hooks/useRealtimeTable";
import type { Run } from "@/lib/rows";

type AppStatus = {
  latestRun: Run | null;
  runs: Run[];
  runsStatus: FeedStatus;
  runsLoaded: boolean;
  health: AgentHealth;
};

const Ctx = createContext<AppStatus | null>(null);

const byStartDesc = (a: Run, b: Run) => (b.started_at ?? "").localeCompare(a.started_at ?? "");

export function AppStatusProvider({ children }: { children: ReactNode }) {
  const runs = useRealtimeTable<Run>({
    key: "shell",
    table: "runs",
    load: async (db) => {
      const { data, error } = await db.from("runs").select("*").order("started_at", { ascending: false }).limit(10);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (r) => r.id,
    sort: byStartDesc,
    max: 10,
    pollMs: 30000,
  });
  const health = useAgentHealth();
  return (
    <Ctx.Provider
      value={{
        latestRun: runs.rows[0] ?? null,
        runs: runs.rows,
        runsStatus: runs.status,
        runsLoaded: runs.loaded,
        health,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAppStatus(): AppStatus {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppStatus outside AppStatusProvider");
  return v;
}
