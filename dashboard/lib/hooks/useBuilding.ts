"use client";

import { useCallback, useEffect, useRef } from "react";
import type { AgentEvent, Asset, Building, BuildingScore, Camera, Coverage, DocumentRow, Fix, TwinNode } from "../rows";
import { selectAll } from "../supabase";
import { useRealtimeTable } from "./useRealtimeTable";

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Everything the building page reads. building_scores streams over Realtime.
 * The other tables are not in the publication, so they refetch whenever an
 * agent_events row for this building arrives (the census is writing), on
 * focus, and on a fast poll while the page waits for a fix.
 */
export function useBuilding(id: string, opts: { waiting?: boolean } = {}) {
  const enabled = UUID_RE.test(id);
  const poll = opts.waiting ? 2000 : undefined;

  const building = useRealtimeTable<Building>({
    key: `bld:${id}`,
    table: "buildings",
    realtime: false,
    enabled,
    load: async (db) => {
      const { data, error } = await db.from("buildings").select("*").eq("id", id).limit(1);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (b) => b.id,
  });

  const nodes = useRealtimeTable<TwinNode>({
    key: `nodes:${id}`,
    table: "twin_nodes",
    realtime: false,
    enabled,
    load: (db) =>
      selectAll<TwinNode>((from, to) =>
        db.from("twin_nodes").select("*").eq("building_id", id).order("sweep_id").range(from, to),
      ),
    rowKey: (n) => n.sweep_id ?? "",
  });

  const assets = useRealtimeTable<Asset>({
    key: `assets:${id}`,
    table: "assets",
    realtime: false,
    enabled,
    pollMs: poll,
    load: (db) =>
      selectAll<Asset>((from, to) => db.from("assets").select("*").eq("building_id", id).order("id").range(from, to)),
    rowKey: (a) => a.id,
  });

  const coverage = useRealtimeTable<Coverage>({
    key: `cov:${id}`,
    table: "coverage",
    realtime: false,
    enabled,
    pollMs: poll,
    load: (db) =>
      selectAll<Coverage>((from, to) =>
        db
          .from("coverage")
          .select("*")
          .eq("building_id", id)
          .order("scenario")
          .order("asset_type")
          .order("sweep_id")
          .range(from, to),
      ),
    rowKey: (c) => `${c.scenario}|${c.asset_type}|${c.sweep_id}`,
  });

  const score = useRealtimeTable<BuildingScore>({
    key: `score:${id}`,
    table: "building_scores",
    filter: `building_id=eq.${id}`,
    enabled,
    load: async (db) => {
      const { data, error } = await db.from("building_scores").select("*").eq("building_id", id).limit(1);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (s) => s.building_id,
  });

  const fixes = useRealtimeTable<Fix>({
    key: `fixes:${id}`,
    table: "fixes",
    realtime: false,
    enabled,
    pollMs: poll,
    load: async (db) => {
      const { data, error } = await db.from("fixes").select("*").eq("building_id", id);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (f) => f.id,
  });

  const documents = useRealtimeTable<DocumentRow>({
    key: `docs:${id}`,
    table: "documents",
    realtime: false,
    enabled,
    pollMs: poll,
    load: async (db) => {
      const { data, error } = await db
        .from("documents")
        .select("*")
        .eq("building_id", id)
        .order("created_at", { ascending: false });
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (d) => d.id,
    sort: (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  });

  const cameras = useRealtimeTable<Camera>({
    key: `cams:${id}`,
    table: "cameras",
    realtime: false,
    enabled,
    load: async (db) => {
      const { data, error } = await db.from("cameras").select("*").eq("building_id", id);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (c) => c.id,
  });

  const timer = useRef<number | null>(null);
  const refetchers = [building.refetch, assets.refetch, coverage.refetch, fixes.refetch, documents.refetch] as const;
  const [rb, ra, rc, rf, rd] = refetchers;
  const refetchCensus = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      rb();
      ra();
      rc();
      rf();
      rd();
    }, 800);
  }, [rb, ra, rc, rf, rd]);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const activity = useRealtimeTable<AgentEvent>({
    key: `act:${id}`,
    table: "agent_events",
    filter: `building_id=eq.${id}`,
    enabled,
    load: async (db) => {
      const { data, error } = await db
        .from("agent_events")
        .select("*")
        .eq("building_id", id)
        .order("id", { ascending: false })
        .limit(20);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (e) => String(e.id),
    sort: (a, b) => b.id - a.id,
    max: 50,
    onChange: refetchCensus,
  });

  return {
    valid: enabled,
    building: building.rows[0] ?? null,
    buildingStatus: building.status,
    buildingLoaded: building.loaded,
    buildingError: building.error,
    nodes: nodes.rows,
    nodesLoaded: nodes.loaded,
    assets: assets.rows,
    coverage: coverage.rows,
    coverageLoaded: coverage.loaded,
    score: score.rows[0] ?? null,
    fixes: fixes.rows,
    documents: documents.rows,
    documentsLoaded: documents.loaded,
    cameras: cameras.rows,
    activity: activity.rows,
    refetchCensus,
  };
}
