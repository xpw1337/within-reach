// JSON payload shapes from docs/CONTRACTS.md section 3 and the jsonb columns in
// the schema. jsonb can hold anything, so every reader here is defensive and
// returns null or [] instead of trusting the shape.
import type { Json } from "./types";

type Obj = { [key: string]: Json | undefined };

export function asObj(v: Json | null | undefined): Obj | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null;
}
export function asStr(v: Json | null | undefined): string | null {
  return typeof v === "string" ? v : null;
}
export function asNum(v: Json | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
export function asBool(v: Json | null | undefined): boolean | null {
  return typeof v === "boolean" ? v : null;
}
export function asArr(v: Json | null | undefined): Json[] {
  return Array.isArray(v) ? v : [];
}

// ---------- agent_events ----------

export type TodoStatus = "pending" | "in_progress" | "done";
export type Todo = { text: string; status: TodoStatus };

export function readTodos(payload: Json | null): Todo[] {
  const todos = asArr(asObj(payload)?.todos);
  const out: Todo[] = [];
  for (const t of todos) {
    const o = asObj(t);
    const text = asStr(o?.text) ?? asStr(o?.content);
    if (!text) continue;
    const s = asStr(o?.status);
    out.push({ text, status: s === "done" || s === "in_progress" ? s : s === "completed" ? "done" : "pending" });
  }
  return out;
}

export function readDecision(payload: Json | null) {
  const o = asObj(payload);
  return {
    reason: asStr(o?.reason),
    detectionId: asStr(o?.detection_id),
    sweepId: asStr(o?.sweep_id),
    options: asArr(o?.options)
      .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
      .filter(Boolean),
  };
}

export function readToolCall(payload: Json | null) {
  const o = asObj(payload);
  return { tool: asStr(o?.tool), args: o?.args ?? null };
}

export function readResult(payload: Json | null) {
  const o = asObj(payload);
  return { tool: asStr(o?.tool), summary: asStr(o?.summary) };
}

export function readWarning(payload: Json | null) {
  const o = asObj(payload);
  return { code: asStr(o?.code), detail: asStr(o?.detail) };
}

// ---------- incident_events ----------

export function readSpeak(payload: Json | null) {
  const o = asObj(payload);
  return {
    scriptId: asStr(o?.script_id),
    text: asStr(o?.text),
    audioUrl: asStr(o?.audio_url),
    target: asStr(o?.target),
  };
}

export function readConfirmRequested(payload: Json | null) {
  const o = asObj(payload);
  return { autoProceedAt: asStr(o?.auto_proceed_at), escalateAt: asStr(o?.escalate_at) };
}

export function readClassified(payload: Json | null) {
  const o = asObj(payload);
  return {
    type: asStr(o?.type),
    modifiers: asArr(o?.modifiers).map(asStr).filter((x): x is string => Boolean(x)),
    sceneSafe: asBool(o?.scene_safe),
    hazards: asArr(o?.hazards).map(asStr).filter((x): x is string => Boolean(x)),
  };
}

export function readTimerStarted(payload: Json | null) {
  const o = asObj(payload);
  return { timer: asStr(o?.timer), firesAt: asStr(o?.fires_at) };
}

export function readEmsBriefed(payload: Json | null) {
  const o = asObj(payload);
  return { briefingText: asStr(o?.briefing_text), emsDoor: readPoint(o?.ems_door ?? null) };
}

// ---------- buildings.vexcel / buildings.ems_door ----------

export type GeoPoint = { lat: number | null; lng: number | null; desc: string | null; reason: string | null };

/** A point from Vexcel data or the EMS door: {lat, lng, desc?, reason?}. */
export function readPoint(v: Json | null | undefined): GeoPoint | null {
  const o = asObj(v);
  if (!o) return null;
  return {
    lat: asNum(o.lat),
    lng: asNum(o.lng ?? o.lon),
    desc: asStr(o.desc) ?? asStr(o.description) ?? asStr(o.label) ?? asStr(o.name),
    reason: asStr(o.reason),
  };
}

export function readVexcel(v: Json | null) {
  const o = asObj(v);
  const points = (key: string) =>
    asArr(o?.[key])
      .map((p) => readPoint(p))
      .filter((p): p is GeoPoint => p !== null);
  return {
    entrances: points("entrances"),
    ambulanceParking: points("ambulance_parking"),
    hydrants: points("hydrants"),
    imageUrl: asStr(o?.image_url),
  };
}

// ---------- incidents.verification ----------

export function readVerification(v: Json | null) {
  const o = asObj(v);
  if (!o) return null;
  return {
    isEmergency: asBool(o.is_emergency),
    sceneSafe: asBool(o.scene_safe),
    hazards: asArr(o.hazards).map(asStr).filter((x): x is string => Boolean(x)),
    modifiers: asArr(o.modifiers).map(asStr).filter((x): x is string => Boolean(x)),
  };
}
