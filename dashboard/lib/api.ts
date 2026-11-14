// Typed wrappers for every endpoint in docs/CONTRACTS.md section 2.
// Calls go to /agent-api/*, which next.config.ts rewrites to NEXT_PUBLIC_AGENT_URL.
// No wrapper throws: each returns an ApiResult so pages can show an empty or
// error state when the agent is not running.
import { agentConfigured } from "./env";
import type { Run } from "./rows";

export const API_BASE = "/agent-api";

export type ApiFailure = {
  ok: false;
  reason: "not_configured" | "unreachable" | "timeout" | "http" | "bad_response";
  error: string;
  status?: number;
};
export type ApiResult<T> = { ok: true; data: T } | ApiFailure;

type RequestOptions = { timeoutMs?: number; signal?: AbortSignal };

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  opts: RequestOptions = {},
): Promise<ApiResult<T>> {
  if (!agentConfigured) {
    return { ok: false, reason: "not_configured", error: "NEXT_PUBLIC_AGENT_URL is not set" };
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 10000);
  opts.signal?.addEventListener("abort", () => controller.abort(), { once: true });
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await res.text();
    let json: unknown = null;
    if (text) {
      try {
        json = JSON.parse(text);
      } catch {
        json = null;
      }
    }
    if (!res.ok) {
      const detail =
        json && typeof json === "object" && "detail" in json ? String((json as { detail: unknown }).detail) : "";
      // The Next proxy answers 5xx with a non-JSON body when the agent is down.
      if (!detail && res.status >= 500) {
        return { ok: false, reason: "unreachable", status: res.status, error: "Agent API is not reachable" };
      }
      return { ok: false, reason: "http", status: res.status, error: detail || `HTTP ${res.status}` };
    }
    if (json === null && text) {
      return { ok: false, reason: "bad_response", status: res.status, error: "Response was not JSON" };
    }
    return { ok: true, data: json as T };
  } catch (e) {
    if (controller.signal.aborted) {
      return { ok: false, reason: "timeout", error: "Agent API did not answer in time" };
    }
    return { ok: false, reason: "unreachable", error: e instanceof Error ? e.message : "Network error" };
  } finally {
    clearTimeout(timeout);
  }
}

/** Twilio webhooks are form-encoded in and TwiML out. Wrapped for completeness and testing. */
async function requestTwiml(path: string, form: Record<string, string>): Promise<ApiResult<string>> {
  if (!agentConfigured) {
    return { ok: false, reason: "not_configured", error: "NEXT_PUBLIC_AGENT_URL is not set" };
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(form).toString(),
      cache: "no-store",
    });
    const text = await res.text();
    if (!res.ok) return { ok: false, reason: "http", status: res.status, error: text || `HTTP ${res.status}` };
    return { ok: true, data: text };
  } catch (e) {
    return { ok: false, reason: "unreachable", error: e instanceof Error ? e.message : "Network error" };
  }
}

const enc = encodeURIComponent;

// ---------- Census ----------

export type City = "Houston" | "Los Angeles";
export type StartRunBody = { buildings_target: number; city?: City; types?: string[]; budget_usd: number };
export type DocumentKind = "owner_letter" | "emergency_card" | "registry_list";
export type ApiDocument = { id: string; kind: DocumentKind; content_md: string; created_at: string };
export type HandcheckItem = {
  detection_id: string;
  asset_type: string;
  crop_url: string | null;
  confidence: number | null;
  status: string | null;
};
export type HumanLabel = "correct" | "incorrect" | "unsure";
export type HandcheckSummary = { labeled: number; correct: number; incorrect: number; unsure: number };
export type Thresholds = {
  walk_speed_mps: number;
  aed_roundtrip_target_s: number;
  ext_max_travel_m: number;
  exit_max_travel_m: number;
  yellow_fraction: number;
};

export const api = {
  startRun: (body: StartRunBody) => request<{ run_id: string }>("POST", "/census/runs", body),
  getRun: (id: string) => request<Run>("GET", `/census/runs/${enc(id)}`),
  stopRun: (id: string) => request<{ status: "stopping" }>("POST", `/census/runs/${enc(id)}/stop`),
  rerunBuilding: (id: string) => request<{ run_id: string }>("POST", `/census/buildings/${enc(id)}/rerun`),
  fixBuilding: (id: string, body: { asset_type?: "aed" | "extinguisher" } = {}) =>
    request<{ fix_id: string }>("POST", `/census/buildings/${enc(id)}/fix`, body, { timeoutMs: 120000 }),
  getDocuments: (id: string) => request<ApiDocument[]>("GET", `/census/buildings/${enc(id)}/documents`),
  getHandcheck: (n = 30) => request<HandcheckItem[]>("GET", `/census/handcheck?n=${n}`),
  labelDetection: (id: string, human_label: HumanLabel) =>
    request<{ ok: true }>("POST", `/census/detections/${enc(id)}/label`, { human_label }),
  getHandcheckSummary: () => request<HandcheckSummary>("GET", "/census/handcheck/summary"),
  getThresholds: () => request<Thresholds>("GET", "/config/thresholds", undefined, { timeoutMs: 5000 }),

  // ---------- Live ----------
  postEvent: (body: {
    camera_id: string;
    kind: "person_down" | "responsive" | "possible_seizure" | "responder_arrived";
    victim_track_id: number;
    witnessed?: boolean;
    ts: string;
    frame_jpeg_b64?: string;
  }) => request<{ incident_id: string | null; status: string }>("POST", "/events", body),
  confirmIncident: (id: string, decision: "confirm" | "false_alarm", by: string) =>
    request<{ status: string }>("POST", `/incidents/${enc(id)}/confirm`, { decision, by }),
  cancel911: (id: string, by: string) => request<{ ok: true }>("POST", `/incidents/${enc(id)}/cancel_911`, { by }),
  milestone: (id: string, kind: "cpr_started" | "aed_arrived" | "responder_arrived", by?: string) =>
    request<{ ok: true }>("POST", `/incidents/${enc(id)}/milestone`, { kind, by }),
  resolveIncident: (id: string, by: string) =>
    request<{ status: "resolved" }>("POST", `/incidents/${enc(id)}/resolve`, { by }),
  acceptDispatch: (id: string) =>
    request<{ role: "patient" | "aed_runner" | "staff"; status: "accepted" } | { status: "released" }>(
      "POST",
      `/dispatches/${enc(id)}/accept`,
    ),
  declineDispatch: (id: string) => request<{ status: "declined" }>("POST", `/dispatches/${enc(id)}/decline`),
  arrivedDispatch: (id: string, with_aed?: boolean) =>
    request<{ status: "arrived" }>("POST", `/dispatches/${enc(id)}/arrived`, { with_aed }),
  twilioVoice: (dispatchId: string, form: Record<string, string> = {}) =>
    requestTwiml(`/twilio/voice/${enc(dispatchId)}`, form),
  twilioGather: (dispatchId: string, digits: string) =>
    requestTwiml(`/twilio/gather/${enc(dispatchId)}`, { Digits: digits }),
  twilioBriefing: (incidentId: string, form: Record<string, string> = {}) =>
    requestTwiml(`/twilio/briefing/${enc(incidentId)}`, form),
  simulate: (kind: "cardiac" | "fall" | "outdoor", camera_id?: string) =>
    request<{ incident_id: string }>("POST", `/simulate/${kind}`, camera_id ? { camera_id } : {}),
  reset: () => request<{ ok: true }>("POST", "/reset", undefined, { timeoutMs: 20000 }),
  health: () =>
    request<{ ok: boolean; warmed: { llm: boolean; tts: boolean; db: boolean }; metrics?: Record<string, unknown> }>("GET", "/health", undefined, {
      timeoutMs: 4000,
    }),
};
