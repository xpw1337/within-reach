// Pure helpers for the /live page. Every time shown is computed from incidents
// and incident_events rows (docs/CONTRACTS.md section 3).
import { asObj, readClassified, readConfirmRequested, readSpeak, readTimerStarted } from "./contracts";
import { copy } from "./copy";
import { humanize, secondsBetween } from "./format";
import type { Incident, IncidentEvent } from "./rows";

export function incidentTitle(i: Incident): string {
  if (i.type === "cardiac") return copy.possibleCardiac;
  if (i.type === "fall") return copy.fall;
  if (i.type === "fire") return "Fire";
  return copy.personDown;
}

/** The zero point for offsets: collapse when known, else detection. */
export function originOf(i: Incident): { ts: string | null; label: string } {
  if (i.collapse_at) return { ts: i.collapse_at, label: "after collapse" };
  return { ts: i.created_at, label: "after detection" };
}

export type Latency = { key: string; label: string; seconds: number | null };

export function latencies(i: Incident): Latency[] {
  const o = originOf(i).ts;
  const at = (ts: string | null) => secondsBetween(o, ts);
  return [
    { key: "first_instruction_at", label: "First instruction", seconds: at(i.first_instruction_at) },
    { key: "confirmed_at", label: "Desk confirm", seconds: at(i.confirmed_at) },
    { key: "ems_notified_at", label: "911 briefed", seconds: at(i.ems_notified_at) },
    { key: "first_accept_at", label: "First responder accepted", seconds: at(i.first_accept_at) },
    { key: "responder_arrived_at", label: "Responder arrived", seconds: at(i.responder_arrived_at) },
    { key: "cpr_started_at", label: "CPR started", seconds: at(i.cpr_started_at) },
    { key: "aed_arrived_at", label: "AED arrived", seconds: at(i.aed_arrived_at) },
  ];
}

export type ConfirmState = { pending: boolean; deadline: string | null; mode: "auto" | "escalate" | null };

/** Is the desk being asked to confirm, and until when (from the confirm_requested payload)? */
export function confirmState(i: Incident | null, events: IncidentEvent[]): ConfirmState {
  const none: ConfirmState = { pending: false, deadline: null, mode: null };
  if (!i || i.status === "resolved" || i.status === "false_alarm" || i.confirmed_at) return none;
  let lastReq = -1;
  for (let k = events.length - 1; k >= 0; k--) {
    if (events[k].kind === "confirm_requested") {
      lastReq = k;
      break;
    }
  }
  if (lastReq < 0) return i.status === "awaiting_confirm" ? { pending: true, deadline: null, mode: null } : none;
  for (let k = lastReq + 1; k < events.length; k++) {
    if (["confirmed", "false_alarm", "gate_opened", "resolved"].includes(events[k].kind ?? "")) return none;
  }
  const p = readConfirmRequested(events[lastReq].payload);
  if (p.autoProceedAt) return { pending: true, deadline: p.autoProceedAt, mode: "auto" };
  if (p.escalateAt) return { pending: true, deadline: p.escalateAt, mode: "escalate" };
  return { pending: true, deadline: null, mode: null };
}

/** FALL playbook: the 911 briefing timer the desk can still cancel. */
export function fall911Timer(i: Incident | null, events: IncidentEvent[]): { firesAt: string } | null {
  if (!i || i.type !== "fall" || i.ems_notified_at || i.status === "resolved" || i.status === "false_alarm") return null;
  if (events.some((e) => e.kind === "fall_911_cancelled")) return null;
  let firesAt: string | null = null;
  for (const e of events) {
    if (e.kind === "timer_started") {
      const t = readTimerStarted(e.payload);
      if (t.timer && t.timer.startsWith("fall_911") && t.firesAt) firesAt = t.firesAt;
    }
    if (e.kind === "timer_fired") {
      const name = asObj(e.payload)?.timer;
      if (typeof name === "string" && name.startsWith("fall_911")) firesAt = null;
    }
  }
  return firesAt ? { firesAt } : null;
}

/** The latest speak event that names a route target, for the fly-through. */
export function latestRouteSpeak(events: IncidentEvent[]): { id: number; target: string; text: string | null } | null {
  for (let k = events.length - 1; k >= 0; k--) {
    const e = events[k];
    if (e.kind !== "speak") continue;
    const s = readSpeak(e.payload);
    if (s.target) return { id: e.id, target: s.target, text: s.text };
  }
  return null;
}

function compact(payload: unknown): string {
  const o = payload && typeof payload === "object" && !Array.isArray(payload) ? (payload as Record<string, unknown>) : null;
  if (!o) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(o)) {
    if (parts.length >= 3) break;
    if (typeof v === "string" && v.length <= 60) parts.push(`${humanize(k)}: ${v}`);
    else if (typeof v === "number" || typeof v === "boolean") parts.push(`${humanize(k)}: ${String(v)}`);
  }
  return parts.join(", ");
}

/** One line per timeline event. Unknown kinds fall back to the kind and simple payload fields. */
export function describeEvent(e: IncidentEvent, who: (actor: string | null) => string): string {
  const p = asObj(e.payload);
  switch (e.kind) {
    case "speak": {
      const s = readSpeak(e.payload);
      return `Speaker: ${s.text ?? humanize(s.scriptId)}`;
    }
    case "classified": {
      const c = readClassified(e.payload);
      const mods = c.modifiers.length ? ` + ${c.modifiers.join(", ")}` : "";
      const unsafe = c.sceneSafe === false ? ", scene unsafe" : "";
      return `Classified ${humanize(c.type)}${mods}${unsafe}`;
    }
    case "confirm_requested":
      return "Desk asked to confirm";
    case "confirmed":
      return `Confirmed by ${typeof p?.by === "string" ? p.by : who(e.actor)}`;
    case "false_alarm":
      return `Marked false alarm by ${typeof p?.by === "string" ? p.by : who(e.actor)}`;
    case "gate_opened":
      return "Responders and 911 briefing released";
    case "ems_briefed":
      return "911 briefing delivered, with the EMS door";
    case "police_notified":
      return "Police notified";
    case "staff_alerted":
      return "Staff alerted";
    case "resolved":
      return "Incident resolved";
    case "dispatch_sent":
    case "dispatch_accepted":
    case "dispatch_declined":
    case "dispatch_timeout":
    case "dispatch_released": {
      const rid = typeof p?.responder_id === "string" ? p.responder_id : null;
      const role = typeof p?.role === "string" ? ` as ${humanize(p.role)}` : "";
      const name = rid ? who(`responder:${rid}`) : e.actor?.startsWith("responder:") ? who(e.actor) : "";
      return `${humanize(e.kind?.replace("dispatch_", "alert "))}${name ? `: ${name}` : ""}${role}`;
    }
    default: {
      const rest = compact(e.payload);
      return `${humanize(e.kind)}${rest ? ` (${rest})` : ""}`;
    }
  }
}
