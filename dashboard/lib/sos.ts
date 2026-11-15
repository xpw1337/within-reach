"use client";

import { useEffect, useRef, useState } from "react";

// The live SOS state from the agent (agent/sos/hub.py console_state), over /sos/ws/console.

export type LatLng = { lat: number; lng: number };
export type Step = { text: string; distance_m: number };
export type Leg = {
  kind: "extinguisher" | "aed" | "person";
  to: LatLng & { label?: string | null; id?: string | null };
  geometry: [number, number][];
  distance_m: number;
  duration_s: number;
  steps: Step[];
  source: "valhalla" | "direct";
  avoids_fire?: boolean;
  fire_on_route?: boolean;
};
export type Place = LatLng & { id: string; kind: "aed" | "extinguisher"; label: string; source: string; distance_m?: number };
export type Offer = {
  id: string;
  responder_id: string;
  name: string;
  status: "sent" | "accepted" | "declined" | "timeout" | "cancelled";
  sent_at: number;
  responded_at: number | null;
  distance_m: number | null;
  expires_at: number;
  call?: string;
};
export type CallLine = { who: "ai" | "dispatcher" | "system"; text: string; at: number };
export type Incident = {
  id: string;
  kind: "fall" | "fire";
  camera_id: string;
  status: "alerting" | "en_route" | "on_scene" | "no_responders" | "resolved";
  started_at: number;
  witnessed: boolean | null;
  location: LatLng & { label?: string | null; accuracy_m?: number | null };
  address: string | null;
  has_snapshot: boolean;
  fire: (LatLng & { active: boolean; radius_m: number; source: string; label: string }) | null;
  offers: Offer[];
  responder_id: string | null;
  accepted_at: number | null;
  arrived_at: number | null;
  resolved_at: number | null;
  responder_distance_m?: number;
  resources: { aeds: Place[]; extinguishers: Place[]; status: string; error: string | null };
  plan: { legs: Leg[]; total_m: number; total_s: number; updated_at: number } | null;
  collected: string[];
  call: { status: "dialing" | "connected" | "ended"; lines: CallLine[]; simulated: boolean };
  timeline: { at: number; text: string; kind: string }[];
};
export type Responder = {
  id: string;
  name: string;
  lat: number | null;
  lng: number | null;
  accuracy_m: number | null;
  on_duty: boolean;
  connected: boolean;
  available: boolean;
  callable?: boolean;
  phone?: string | null;
  text_line?: string | null;
  last_seen: number;
};
export type Camera = LatLng & { id: string; accuracy_m: number | null; label: string; source: string; updated_at: number };
export type SosState = {
  server_time: number;
  cameras: Camera[];
  responders: Responder[];
  incident: Incident | null;
  history: { id: string; kind: string; status: string; started_at: number; resolved_at: number | null }[];
  pinned_places: Place[];
  camera_places: { count: number; at: number } | null;
  settings: { accept_timeout_s: number; fire_radius_m: number; calls?: boolean; texts?: boolean };
};

/** Agent URL: NEXT_PUBLIC_AGENT_URL, else the same host as this page on port 8000. */
export function agentUrl(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_AGENT_URL ?? "").replace(/\/+$/, "");
  if (fromEnv) return fromEnv;
  if (typeof window === "undefined") return "";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

/** Annotated camera feed from vision/stream.py: NEXT_PUBLIC_VISION_URL, else this host on port 8001. */
export function visionUrl(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_VISION_URL ?? "").replace(/\/+$/, "");
  if (fromEnv) return fromEnv;
  if (typeof window === "undefined") return "";
  return `${window.location.protocol}//${window.location.hostname}:8001`;
}

export const CAMERA_ID = process.env.NEXT_PUBLIC_CAMERA_ID || "webcam-1";

export async function sosCall<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(agentUrl() + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error((data && (data.detail as string)) || `HTTP ${res.status}`);
  return data as T;
}

export type Link = "connecting" | "live" | "down";

export function useSosState(): { state: SosState | null; link: Link; skewMs: number } {
  const [state, setState] = useState<SosState | null>(null);
  const [link, setLink] = useState<Link>("connecting");
  const [skewMs, setSkew] = useState(0);
  const retry = useRef(1000);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let ping: ReturnType<typeof setInterval> | null = null;
    let closed = false;
    const open = () => {
      setLink("connecting");
      ws = new WebSocket(agentUrl().replace(/^http/, "ws") + "/sos/ws/console");
      ws.onopen = () => {
        retry.current = 1000;
        setLink("live");
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 20000);
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data));
          if (msg.type === "state") {
            setState(msg.state as SosState);
            setSkew((msg.state as SosState).server_time - Date.now());
          }
        } catch {
          // ignore malformed frames
        }
      };
      ws.onclose = () => {
        if (ping) clearInterval(ping);
        if (closed) return;
        setLink("down");
        timer = setTimeout(open, retry.current);
        retry.current = Math.min(retry.current * 2, 8000);
      };
    };
    open();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      if (ping) clearInterval(ping);
      ws?.close();
    };
  }, []);

  return { state, link, skewMs };
}
