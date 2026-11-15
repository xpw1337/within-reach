"use client";

import { useMemo, useState } from "react";
import { useAppStatus } from "@/components/shell/AppStatus";
import { cx, Dot } from "@/components/ui";
import { readTodos } from "@/lib/contracts";
import { copy } from "@/lib/copy";
import { dateTime, int } from "@/lib/format";
import { useRealtimeTable } from "@/lib/hooks/useRealtimeTable";
import { useStoredFlag } from "@/lib/hooks/useStoredFlag";
import type { AgentEvent } from "@/lib/rows";
import { EventRow } from "./EventRow";
import { TodoList } from "./TodoList";

const byIdDesc = (a: AgentEvent, b: AgentEvent) => b.id - a.id;

/**
 * Streams agent_events for the latest run. Lives in the root layout so it is
 * never unmounted between pages. This is what makes the census read as an
 * agent at work rather than a dashboard (spec section 9.12).
 */
export function AgentConsole() {
  const { latestRun, runsLoaded, runsStatus } = useAppStatus();
  const runId = latestRun?.id ?? null;
  const [collapsed, setCollapsed] = useStoredFlag("wr.console.collapsed", false);
  const [decisionsOnly, setDecisionsOnly] = useState(false);

  // The latest run's events plus events with no run (POST /census/buildings/{id}/fix
  // writes run_id NULL). Realtime filters cannot express "is null", so the
  // stream is unfiltered and checked client-side.
  const events = useRealtimeTable<AgentEvent>({
    key: `console:${runId ?? "none"}`,
    table: "agent_events",
    load: async (db) => {
      const q = db.from("agent_events").select("*");
      const { data, error } = await (runId ? q.or(`run_id.eq.${runId},run_id.is.null`) : q.is("run_id", null))
        .order("id", { ascending: false })
        .limit(100);
      if (error) throw new Error(error.message);
      return data ?? [];
    },
    accept: (e) => e.run_id === null || e.run_id === runId,
    rowKey: (e) => String(e.id),
    sort: byIdDesc,
    max: 400,
  });

  const { todos, stream, decisions } = useMemo(() => {
    const latestTodo = events.rows.find((e) => e.kind === "todo");
    const nonTodo = events.rows.filter((e) => e.kind !== "todo");
    return {
      todos: latestTodo ? readTodos(latestTodo.payload) : [],
      stream: nonTodo,
      decisions: nonTodo.filter((e) => e.kind === "decision").length,
    };
  }, [events.rows]);

  const shown = decisionsOnly ? stream.filter((e) => e.kind === "decision") : stream;
  const newest = stream[0];
  const liveTone =
    events.status === "live" ? "ok" : events.status === "error" ? "down" : events.status === "unconfigured" ? "idle" : "warn";

  if (collapsed) {
    return (
      <aside data-agent-console className="flex shrink-0 border-t border-line bg-panel lg:w-12 lg:flex-col lg:border-t-0 lg:border-l">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="flex flex-1 items-center gap-3 px-4 py-2 text-left lg:flex-col lg:px-0 lg:py-4"
          aria-label="Open agent console"
        >
          <Dot tone={liveTone} />
          <span className="label lg:[writing-mode:vertical-rl]">Agent console</span>
          {newest && (
            <span className="truncate text-xs text-muted lg:hidden">{newest.message}</span>
          )}
        </button>
      </aside>
    );
  }

  return (
    <aside data-agent-console className="flex max-h-[42vh] shrink-0 flex-col border-t border-line bg-panel lg:max-h-none lg:w-[400px] lg:border-t-0 lg:border-l 2xl:w-[440px]">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <Dot tone={liveTone} />
        <h2 className="text-sm font-bold tracking-tight">Agent console</h2>
        {latestRun && (
          <span className="text-xs text-muted">
            run {latestRun.status ?? "--"} since {dateTime(latestRun.started_at)}
          </span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="ml-auto rounded px-1.5 py-0.5 text-xs font-semibold text-muted hover:text-text"
          aria-label="Collapse agent console"
        >
          Hide
        </button>
      </header>

      {(runId || stream.length > 0) && (
        <div className="flex items-center gap-3 border-b border-line px-4 py-1.5 text-xs text-muted">
          <span>
            <span className="num text-text">{int(stream.length)}</span> events
          </span>
          <span>
            <span className="num text-decision">{int(decisions)}</span> decisions
          </span>
          <label className="ml-auto flex cursor-pointer items-center gap-1.5">
            <input
              type="checkbox"
              checked={decisionsOnly}
              onChange={(e) => setDecisionsOnly(e.target.checked)}
              className="accent-[var(--decision)]"
            />
            Decisions only
          </label>
        </div>
      )}

      <TodoList todos={todos} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {events.status === "unconfigured" || runsStatus === "unconfigured" ? (
          <Empty>{copy.supabaseMissing}</Empty>
        ) : !runId && events.loaded && stream.length === 0 && todos.length === 0 ? (
          <Empty>{runsLoaded ? copy.noRun : "Connecting"}</Empty>
        ) : events.status === "error" ? (
          <Empty>Could not load agent events: {events.error}</Empty>
        ) : !events.loaded ? (
          <Empty>Loading</Empty>
        ) : shown.length === 0 ? (
          <Empty>{decisionsOnly ? "No decisions in this run yet." : "Waiting for the agent."}</Empty>
        ) : (
          <ul className={cx("text-sm")}>
            {shown.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-6 text-sm text-muted">{children}</div>;
}
