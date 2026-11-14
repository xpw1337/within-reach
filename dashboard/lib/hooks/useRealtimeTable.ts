"use client";

import type { RealtimeChannel, RealtimePostgresChangesPayload } from "@supabase/supabase-js";
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import type { PublishedTable } from "../rows";
import { getSupabase, type DB } from "../supabase";
import type { Database } from "../types";

type TableName = keyof Database["public"]["Tables"];

const PUBLISHED = new Set<string>([
  "agent_events",
  "runs",
  "building_scores",
  "incidents",
  "incident_events",
  "dispatches",
  "responders",
] satisfies PublishedTable[]);

export type FeedStatus = "unconfigured" | "idle" | "loading" | "live" | "ready" | "reconnecting" | "error";

export type RealtimeTableOptions<Row> = {
  /** Distinguishes consumers of the same table; part of the channel topic. */
  key: string;
  table: TableName;
  /** Initial load and every refetch. Should apply the same filter as `filter`. */
  load: (db: DB) => Promise<Row[]>;
  /** Primary key of a row. DELETE payloads only carry primary key columns. */
  rowKey: (row: Row) => string;
  /** Realtime filter, e.g. "incident_id=eq.<uuid>". */
  filter?: string;
  /** Extra client-side check for streamed rows. */
  accept?: (row: Row) => boolean;
  sort?: (a: Row, b: Row) => number;
  /** Keep the first N rows after sorting. */
  max?: number;
  enabled?: boolean;
  /** Subscribe to Realtime. Defaults to whether the table is in the publication. */
  realtime?: boolean;
  /** Refetch on this interval when Realtime is not live (or always for unpublished tables). */
  pollMs?: number;
  /** Called after a streamed change has been applied. */
  onChange?: (payload: RealtimePostgresChangesPayload<Record<string, unknown>>) => void;
};

export type RealtimeTable<Row> = {
  rows: Row[];
  status: FeedStatus;
  error: string | null;
  /** True once the first load for the current key and filter has finished. */
  loaded: boolean;
  refetch: () => void;
};

type State<Row> = { identity: string; rows: Row[]; status: FeedStatus; error: string | null; loaded: boolean };

/**
 * Rows of one table, loaded once and then kept current through Realtime.
 * Realtime can drop on venue Wi-Fi, so it also refetches when the channel
 * resubscribes, when the tab regains focus or comes back online, and on an
 * optional poll while the channel is not live.
 */
export function useRealtimeTable<Row>(opts: RealtimeTableOptions<Row>): RealtimeTable<Row> {
  const { key, table, filter, enabled = true, pollMs } = opts;
  const realtime = opts.realtime ?? PUBLISHED.has(table);
  const db = getSupabase();
  const identity = `${table}|${key}|${filter ?? ""}`;

  const [state, setState] = useState<State<Row>>({
    identity: "",
    rows: [],
    status: "loading",
    error: null,
    loaded: false,
  });
  const loadRef = useRef<(() => void) | null>(null);

  const runLoad = useEffectEvent((client: DB) => opts.load(client));
  const keyOf = useEffectEvent((row: Row) => opts.rowKey(row));
  const accepts = useEffectEvent((row: Row) => (opts.accept ? opts.accept(row) : true));
  const ordered = useEffectEvent((map: Map<string, Row>) => {
    let rows = [...map.values()];
    if (opts.sort) rows.sort(opts.sort);
    if (opts.max && rows.length > opts.max) {
      rows = rows.slice(0, opts.max);
      map.clear();
      for (const r of rows) map.set(opts.rowKey(r), r);
    }
    return rows;
  });
  const changed = useEffectEvent((payload: RealtimePostgresChangesPayload<Record<string, unknown>>) => {
    opts.onChange?.(payload);
  });

  useEffect(() => {
    if (!enabled || !db) return;
    let cancelled = false;
    let loading = false;
    let again = false;
    let live = false;
    let everSubscribed = false;
    let lastLoad = 0;
    let map = new Map<string, Row>();
    let duringLoad: RealtimePostgresChangesPayload<Record<string, unknown>>[] = [];

    const apply = (target: Map<string, Row>, p: RealtimePostgresChangesPayload<Record<string, unknown>>) => {
      if (p.eventType === "DELETE") {
        const old = p.old as unknown as Row;
        target.delete(keyOf(old));
        return;
      }
      const row = p.new as unknown as Row;
      if (accepts(row)) target.set(keyOf(row), row);
      else target.delete(keyOf(row));
    };

    const publish = (status: FeedStatus, error: string | null, loaded: boolean) => {
      const rows = ordered(map);
      setState({ identity, rows, status, error, loaded });
    };

    const load = async () => {
      if (cancelled) return;
      if (loading) {
        again = true;
        return;
      }
      loading = true;
      lastLoad = Date.now();
      duringLoad = [];
      try {
        const data = await runLoad(db);
        if (cancelled) return;
        const next = new Map<string, Row>();
        for (const row of data) next.set(keyOf(row), row);
        for (const p of duringLoad) apply(next, p);
        map = next;
        publish(realtime ? (live ? "live" : "reconnecting") : "ready", null, true);
      } catch (e) {
        if (cancelled) return;
        setState((s) => ({
          identity,
          rows: s.identity === identity ? s.rows : [],
          status: "error",
          error: e instanceof Error ? e.message : String(e),
          loaded: s.identity === identity ? s.loaded : false,
        }));
      } finally {
        loading = false;
        duringLoad = [];
        if (again && !cancelled) {
          again = false;
          void load();
        }
      }
    };
    loadRef.current = () => void load();

    let channel: RealtimeChannel | null = null;
    if (realtime) {
      channel = db
        .channel(`rt:${identity}:${Math.random().toString(36).slice(2, 8)}`)
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table, ...(filter ? { filter } : {}) },
          (payload: RealtimePostgresChangesPayload<Record<string, unknown>>) => {
            if (cancelled) return;
            if (loading) duringLoad.push(payload);
            apply(map, payload);
            publish("live", null, true);
            changed(payload);
          },
        )
        .subscribe((status) => {
          if (cancelled) return;
          if (status === "SUBSCRIBED") {
            live = true;
            // A resubscribe means we may have missed changes while offline.
            if (everSubscribed) void load();
            everSubscribed = true;
            setState((s) => (s.identity === identity && s.loaded ? { ...s, status: "live" } : s));
          } else {
            live = false;
            setState((s) => (s.identity === identity ? { ...s, status: "reconnecting" } : s));
          }
        });
    }

    void load();

    const refresh = () => {
      if (Date.now() - lastLoad > 1500) void load();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    document.addEventListener("visibilitychange", onVisible);
    const poll = pollMs
      ? window.setInterval(() => {
          if (!realtime || !live) void load();
        }, pollMs)
      : undefined;

    return () => {
      cancelled = true;
      loadRef.current = null;
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
      document.removeEventListener("visibilitychange", onVisible);
      if (poll) window.clearInterval(poll);
      if (channel) void db.removeChannel(channel);
    };
  }, [db, table, filter, enabled, realtime, pollMs, identity]);

  const refetch = useCallback(() => loadRef.current?.(), []);

  if (!db) return { rows: [], status: "unconfigured", error: null, loaded: false, refetch };
  if (!enabled) return { rows: [], status: "idle", error: null, loaded: false, refetch };
  if (state.identity !== identity) return { rows: [], status: "loading", error: null, loaded: false, refetch };
  return { rows: state.rows, status: state.status, error: state.error, loaded: state.loaded, refetch };
}
