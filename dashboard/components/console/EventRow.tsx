import Link from "next/link";
import { cx } from "@/components/ui";
import { readDecision, readResult, readToolCall, readWarning } from "@/lib/contracts";
import { clock } from "@/lib/format";
import type { AgentEvent } from "@/lib/rows";

const AGENT_COLORS: Record<string, string> = {
  planner: "#5cc8ff",
  records: "#b18cff",
  scanner: "#7aa2ff",
  mapper: "#3dd6c6",
  outside: "#f78fb3",
  fixer: "#ffa26b",
};

export function AgentTag({ agent }: { agent: string | null }) {
  const color = (agent && AGENT_COLORS[agent]) || "#93a0b2";
  return (
    <span
      className="inline-block rounded px-1.5 py-px text-[0.66rem] font-bold uppercase tracking-wider"
      style={{ color, backgroundColor: `${color}1f`, boxShadow: `inset 0 0 0 1px ${color}55` }}
    >
      {agent ?? "agent"}
    </span>
  );
}

function argsPreview(args: unknown): string {
  if (args === null || args === undefined) return "";
  try {
    const s = typeof args === "string" ? args : JSON.stringify(args);
    return s.length > 140 ? `${s.slice(0, 137)}...` : s;
  } catch {
    return "";
  }
}

export function EventRow({ event }: { event: AgentEvent }) {
  const kind = event.kind ?? "event";
  const isDecision = kind === "decision";
  const isWarning = kind === "warning";
  const isTool = kind === "tool_call";

  let detail: React.ReactNode = null;
  if (isDecision) {
    const d = readDecision(event.payload);
    detail = (
      <>
        {d.reason && d.reason !== event.message && (
          <div className="mt-1 text-[0.8rem] text-text/85">
            <span className="font-semibold text-decision">Why: </span>
            {d.reason}
          </div>
        )}
        {d.options.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {d.options.slice(0, 6).map((o, i) => (
              <span key={i} className="rounded border border-decision/30 px-1.5 py-px text-[0.7rem] text-muted">
                {o}
              </span>
            ))}
          </div>
        )}
      </>
    );
  } else if (isTool) {
    const t = readToolCall(event.payload);
    const a = argsPreview(t.args);
    if (a) detail = <div className="num mt-0.5 truncate text-[0.72rem] text-faint">{a}</div>;
  } else if (kind === "result") {
    const r = readResult(event.payload);
    if (r.summary && r.summary !== event.message) {
      detail = <div className="mt-0.5 text-[0.78rem] text-muted">{r.summary}</div>;
    }
  } else if (isWarning) {
    const w = readWarning(event.payload);
    if (w.detail && w.detail !== event.message) {
      detail = <div className="mt-0.5 text-[0.78rem] text-warn/90">{w.detail}</div>;
    }
  }

  return (
    <li
      className={cx(
        "flash-in border-b border-line/70 px-4 py-2.5",
        isDecision && "border-l-[3px] border-l-decision bg-decision/[0.07] pl-[13px]",
        isWarning && "border-l-[3px] border-l-warn bg-warn/[0.06] pl-[13px]",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="num text-[0.7rem] text-faint">{clock(event.ts)}</span>
        <AgentTag agent={event.agent} />
        <span
          className={cx(
            "text-[0.66rem] font-bold uppercase tracking-wider",
            isDecision ? "text-decision" : isWarning ? "text-warn" : "text-faint",
          )}
        >
          {isTool ? "tool" : kind}
        </span>
        {event.building_id && (
          <Link
            href={`/building/${event.building_id}`}
            className="ml-auto text-[0.7rem] text-muted underline decoration-line-strong underline-offset-2 hover:text-accent"
          >
            building
          </Link>
        )}
      </div>
      <div
        className={cx(
          "mt-1 leading-snug",
          isDecision ? "text-[0.92rem] font-semibold text-text" : isTool ? "num text-[0.78rem] text-muted" : "text-[0.86rem] text-text/90",
        )}
      >
        {event.message ?? ""}
      </div>
      {detail}
    </li>
  );
}
