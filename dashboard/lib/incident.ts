// Pure helpers for the /live page. Every time shown is computed from incidents
// and incident_events rows (docs/CONTRACTS.md section 3).
import { asObj, readClassified, readConfirmRequested, readSpeak, readTimerStarted } from "./contracts";
import { copy, milestoneLabel, roleLabel } from "./copy";
import { humanize, secondsBetween } from "./format";
import { isSimulated, type Asset, type Dispatch, type Incident, type IncidentEvent } from "./rows";

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

/** First ring: the earliest dispatches.sent_at with a call_sid (CONTRACTS section 3). */
export function firstRingAt(dispatches: Pick<Dispatch, "sent_at" | "call_sid">[]): string | null {
  let best: string | null = null;
  for (const d of dispatches) {
    if (!d.call_sid || !d.sent_at) continue;
    if (best === null || Date.parse(d.sent_at) < Date.parse(best)) best = d.sent_at;
  }
  return best;
}

export function latencies(i: Incident, dispatches: Pick<Dispatch, "sent_at" | "call_sid">[] = []): Latency[] {
  const o = originOf(i).ts;
  const at = (ts: string | null) => secondsBetween(o, ts);
  return [
    { key: "first_instruction_at", label: "First instruction", seconds: at(i.first_instruction_at) },
    { key: "first_ring", label: "First phone ringing", seconds: at(firstRingAt(dispatches)) },
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
      if (t.timer === "fall_911" && t.firesAt) firesAt = t.firesAt;
    }
    if (e.kind === "timer_fired") {
      const name = asObj(e.payload)?.timer;
      if (name === "fall_911") firesAt = null;
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
    case "milestone": {
      // {kind, by?}: cpr_started | aed_arrived | responder_arrived | aed_picked_up | aed_help_started.
      const kind = typeof p?.kind === "string" ? p.kind : null;
      return milestoneLabel(kind);
    }
    case "voice_check_result":
      // {responsive}: only a sustained raised hand counts (spec section 3).
      return p?.responsive === true
        ? "Voice check: raised hand, responsive"
        : p?.responsive === false
          ? "Voice check: no raised hand"
          : "Voice check finished";
    case "verify_result": {
      // {is_emergency, scene_safe, hazards[], modifiers[], error?}, after the allowlist filter.
      if (typeof p?.error === "string" && p.error) return `Scene check failed (${p.error}); continuing without it`;
      const parts: string[] = [];
      if (p?.is_emergency === false) parts.push("may not be an emergency (advice only)");
      if (p?.is_emergency === true) parts.push("looks like an emergency");
      if (p?.scene_safe === false) parts.push("scene unsafe");
      const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
      const mods = list(p?.modifiers);
      const hazards = list(p?.hazards);
      if (mods.length) parts.push(`+ ${mods.map(humanize).join(", ")}`);
      if (hazards.length) parts.push(`hazards: ${hazards.map(humanize).join(", ")}`);
      return `Scene check: ${parts.join(", ") || "no changes"}`;
    }
    case "timer_fired":
      return `Timer fired: ${humanize(typeof p?.timer === "string" ? p.timer : null)}`;
    case "dispatch_sent":
    case "dispatch_accepted":
    case "dispatch_declined":
    case "dispatch_timeout":
    case "dispatch_released": {
      // {dispatch_id, responder_id, role, wave, channel, call_sid?}
      const rid = typeof p?.responder_id === "string" ? p.responder_id : null;
      const name = rid ? who(`responder:${rid}`) : e.actor?.startsWith("responder:") ? who(e.actor) : "a responder";
      const role = typeof p?.role === "string" ? ` as ${roleLabel(p.role)}` : "";
      const via = [
        typeof p?.wave === "number" ? `wave ${p.wave}` : null,
        typeof p?.channel === "string" ? humanize(p.channel) : null,
        typeof p?.call_sid === "string" && p.call_sid ? "phone ringing" : null,
      ].filter(Boolean);
      const verb = {
        dispatch_sent: "Alert sent to",
        dispatch_accepted: "Accepted:",
        dispatch_declined: "Declined:",
        dispatch_timeout: "No answer:",
        dispatch_released: "Released:",
      }[e.kind];
      return `${verb} ${name}${role}${via.length ? ` (${via.join(", ")})` : ""}`;
    }
    default: {
      const rest = compact(e.payload);
      return `${humanize(e.kind)}${rest ? ` (${rest})` : ""}`;
    }
  }
}

/**
 * Does this route lead to a demo prop placed by the team? The asset at the
 * route's last sweep decides; with no asset there, the route counts as leading
 * to a demo prop only when every asset of that type in the building is one.
 */
export function routeEndsAtSimulated(
  path: string[],
  target: string,
  assets: Pick<Asset, "type" | "sweep_id" | "source" | "flags">[],
): boolean {
  const types = target === "exit" ? ["exit", "exit_sign"] : [target];
  const own = assets.filter((a) => a.source !== "proposed" && types.includes(a.type));
  if (own.length === 0) return false;
  const end = path.length ? path[path.length - 1] : null;
  const atEnd = end ? own.filter((a) => a.sweep_id === end) : [];
  if (atEnd.length > 0) return atEnd.every((a) => isSimulated(a));
  return own.every((a) => isSimulated(a));
}
