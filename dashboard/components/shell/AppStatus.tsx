"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useAgentHealth, type AgentHealth } from "@/lib/hooks/useAgentHealth";
import { useRealtimeTable, type FeedStatus } from "@/lib/hooks/useRealtimeTable";
import { readRunBuildingIds } from "@/lib/contracts";
import { isCensusRun, isExcludedFromCensus, nonCensusFilter, type Building, type Run } from "@/lib/rows";

type AppStatus = {
  /** Newest run of any kind: the agent console follows it, including a stage rerun of the demo building. */
  latestRun: Run | null;
  /** Newest run that is not only a rerun of fixture or demo buildings: run progress shows this one. */
  latestCensusRun: Run | null;
  /** Ids of fixture and demo buildings (isExcludedFromCensus). */
  excludedBuildingIds: ReadonlySet<string>;
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
  const excluded = useRealtimeTable<Pick<Building, "id" | "costar_property_id">>({
    key: "shell",
    table: "buildings",
    realtime: false,
    load: async (db) => {
      const { data, error } = await db.from("buildings").select("id,costar_property_id").or(nonCensusFilter()).limit(1000);
      if (error) throw new Error(error.message);
      return (data ?? []).filter(isExcludedFromCensus);
    },
    rowKey: (b) => b.id,
  });
  const excludedBuildingIds = useMemo(() => new Set(excluded.rows.map((b) => b.id)), [excluded.rows]);
  const latestCensusRun = useMemo(
    () => runs.rows.find((r) => isCensusRun(readRunBuildingIds(r.notes), excludedBuildingIds)) ?? null,
    [runs.rows, excludedBuildingIds],
  );
  const health = useAgentHealth();
  return (
    <Ctx.Provider
      value={{
        latestRun: runs.rows[0] ?? null,
        latestCensusRun,
        excludedBuildingIds,
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
