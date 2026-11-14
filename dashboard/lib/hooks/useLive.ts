"use client";

import { useMemo } from "react";
import type { Camera, CameraRoute, Dispatch, Incident, IncidentEvent, Responder } from "../rows";
import { useRealtimeTable } from "./useRealtimeTable";

const CLOSED = new Set(["resolved", "false_alarm"]);

export function isOpen(i: Incident | null | undefined): boolean {
  return Boolean(i && !CLOSED.has(i.status ?? ""));
}

/**
 * The /live page state, from Realtime on incidents, incident_events,
 * dispatches and responders. cameras and camera_routes are static seed data.
 */
export function useLive() {
  const incidents = useRealtimeTable<Incident>({
    key: "live",
    table: "incidents",
    load: async (db) => {
      const { data, error } = await db.from("incidents").select("*").order("created_at", { ascending: false }).limit(10);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (i) => i.id,
    sort: (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
    max: 20,
  });

  const current = useMemo(
    () => incidents.rows.find((i) => isOpen(i)) ?? incidents.rows[0] ?? null,
    [incidents.rows],
  );
  const incidentId = current?.id ?? null;

  const events = useRealtimeTable<IncidentEvent>({
    key: "live",
    table: "incident_events",
    filter: incidentId ? `incident_id=eq.${incidentId}` : undefined,
    enabled: Boolean(incidentId),
    load: async (db) => {
      const { data, error } = await db
        .from("incident_events")
        .select("*")
        .eq("incident_id", incidentId as string)
        .order("id", { ascending: true })
        .limit(500);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (e) => String(e.id),
    sort: (a, b) => a.id - b.id,
  });

  const dispatches = useRealtimeTable<Dispatch>({
    key: "live",
    table: "dispatches",
    filter: incidentId ? `incident_id=eq.${incidentId}` : undefined,
    enabled: Boolean(incidentId),
    load: async (db) => {
      const { data, error } = await db.from("dispatches").select("*").eq("incident_id", incidentId as string);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (d) => d.id,
    sort: (a, b) => (a.wave ?? 0) - (b.wave ?? 0) || (a.sent_at ?? "").localeCompare(b.sent_at ?? ""),
  });

  const responders = useRealtimeTable<Responder>({
    key: "live",
    table: "responders",
    load: async (db) => {
      const { data, error } = await db.from("responders").select("*").limit(500);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (r) => r.id,
  });

  const cameras = useRealtimeTable<Camera>({
    key: "live",
    table: "cameras",
    realtime: false,
    load: async (db) => {
      const { data, error } = await db.from("cameras").select("*");
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (c) => c.id,
  });

  const routes = useRealtimeTable<CameraRoute>({
    key: "live",
    table: "camera_routes",
    realtime: false,
    load: async (db) => {
      const { data, error } = await db.from("camera_routes").select("*");
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    rowKey: (r) => `${r.camera_id}|${r.target}`,
  });

  return {
    status: incidents.status,
    loaded: incidents.loaded,
    error: incidents.error,
    current,
    events: events.rows,
    dispatches: dispatches.rows,
    responders: responders.rows,
    cameras: cameras.rows,
    routes: routes.rows,
  };
}
