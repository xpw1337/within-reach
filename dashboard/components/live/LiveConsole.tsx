"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { setAgentWords, type AgentWords } from "@/components/ai-lights/live";
import { Button, cx, Panel } from "@/components/ui";
import { agentUrl, CAMERA_ID, sosCall, useSosState, visionUrl, type Incident, type SosState } from "@/lib/sos";
import type { ClickMode } from "./LiveMap";

const LiveMap = dynamic(() => import("./LiveMap").then((m) => m.LiveMap), { ssr: false });
const AiLightsCard = dynamic(() => import("@/components/ai-lights/card"), { ssr: false });
const VoiceWaveCard = dynamic(() => import("@/components/voice-wave/card"), { ssr: false });

const OPEN: Incident["status"][] = ["alerting", "en_route", "on_scene", "no_responders"];

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function useNow(ms = 500): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** The laptop is the camera: register its location (browser geolocation) once, and on demand. */
function useCameraLocation(state: SosState | null) {
  const [status, setStatus] = useState<string | null>(null);
  const asked = useRef(false);
  const register = () => {
    if (!navigator.geolocation) {
      setStatus("This browser has no location access. Set CAMERA_LAT and CAMERA_LNG for the agent.");
      return;
    }
    setStatus("Finding this laptop's location...");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await sosCall("PUT", `/sos/cameras/${encodeURIComponent(CAMERA_ID)}`, {
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy_m: Math.round(pos.coords.accuracy),
          });
          setStatus(null);
        } catch (e) {
          setStatus(`Could not save the camera location: ${(e as Error).message}`);
        }
      },
      (err) => setStatus(`Location blocked (${err.message}). Allow location for this page, or click the map where the camera is.`),
      { enableHighAccuracy: true, timeout: 15000 },
    );
  };
  useEffect(() => {
    if (!state || asked.current) return;
    asked.current = true;
    if (!state.cameras.some((c) => c.id === CAMERA_ID)) setTimeout(register, 0);
  }, [state]);
  return { status, register };
}

/** What the AI lights card says, from the live incident. */
function agentWords(inc: Incident | null, responderName: string | null): AgentWords {
  if (!inc || !OPEN.includes(inc.status)) {
    return { steps: ["Watch", "Alert", "911"], live: 0, doing: "Watching the camera", cmd: "camera",
      result: "all clear", prompt: "waiting for a fall or fire" };
  }
  const pending = inc.offers.find((o) => o.status === "sent");
  const lastAi = [...inc.call.lines].reverse().find((l) => l.who === "ai");
  const live: 0 | 1 | 2 = inc.status === "alerting" || inc.status === "no_responders" ? 1 : 2;
  const doing = inc.status === "alerting" ? `Alerting ${pending?.name ?? "help"}`
    : inc.status === "no_responders" ? "Finding a responder"
      : inc.status === "en_route" ? `${responderName ?? "Responder"} on the way` : `${responderName ?? "Responder"} is there`;
  return {
    steps: [inc.kind === "fire" ? "Fire" : "Fall", "Alert", "911"],
    live,
    doing: clip(doing, 22),
    cmd: "call 911 --simulated",
    result: clip(lastAi?.text ?? "dialing", 30),
    prompt: clip(`${inc.kind === "fire" ? "fire" : "fall"} at ${inc.location.label ?? "camera"}`, 28),
  };
}

function CameraFeed({ alarm }: { alarm: boolean }) {
  const [ok, setOk] = useState(true);
  const [nonce, setNonce] = useState(0);
  const base = visionUrl();
  useEffect(() => {
    if (ok) return;
    const t = setTimeout(() => {
      setOk(true);
      setNonce((n) => n + 1);
    }, 3000);
    return () => clearTimeout(t);
  }, [ok]);
  return (
    <div className={cx("relative overflow-hidden rounded-2xl border-2 bg-[#111]", alarm ? "border-accent ring-4 ring-accent/25" : "border-line")}>
      {ok ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={nonce} src={`${base}/stream.mjpg?n=${nonce}`} alt="Camera with people and pose overlay"
          className="aspect-video w-full object-contain" onError={() => setOk(false)} />
      ) : (
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 p-6 text-center">
          <div className="text-lg font-extrabold text-white">Camera is off</div>
          <div className="text-sm text-[#aaa]">
            Start it with <code className="num rounded-md bg-white/10 px-1.5 py-0.5">uv run python -m vision.main</code>
          </div>
        </div>
      )}
      <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 text-[0.7rem] font-black uppercase tracking-wider text-accent">
        <span className="inline-block size-2 animate-pulse rounded-full bg-accent" /> Live
      </div>
    </div>
  );
}

function Pill({ tone, children }: { tone: "green" | "red" | "orange" | "grey"; children: React.ReactNode }) {
  const t = { green: "bg-ok/12 text-ok-dark", red: "bg-accent/10 text-accent", orange: "bg-decision/12 text-[#c26600]", grey: "bg-panel-2 text-muted" }[tone];
  return <span className={cx("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-extrabold", t)}>{children}</span>;
}

/** Duolingo-style progress through the response: seen, alerted, accepted, with them. */
function Steps({ inc }: { inc: Incident }) {
  const reached = [true, inc.offers.length > 0, Boolean(inc.accepted_at), Boolean(inc.arrived_at)];
  const labels = ["Seen", "Alerted", "Accepted", "With them"];
  const n = reached.filter(Boolean).length;
  return (
    <div className="flex flex-col gap-2">
      <div className="h-4 overflow-hidden rounded-full bg-raised">
        <div className="relative h-4 rounded-full bg-ok transition-all duration-700" style={{ width: `${(n / 4) * 100}%` }}>
          <div className="absolute inset-x-2 top-1 h-1 rounded-full bg-white/35" />
        </div>
      </div>
      <div className="grid grid-cols-4 text-center text-[0.7rem] font-extrabold uppercase tracking-wide">
        {labels.map((l, i) => <span key={l} className={reached[i] ? "text-ok-dark" : "text-faint"}>{l}</span>)}
      </div>
    </div>
  );
}

function CallTranscript({ incident, speak }: { incident: Incident | null; speak: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const spoken = useRef<string>("");
  const lines = useMemo(() => incident?.call.lines ?? [], [incident]);
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" });
  }, [lines.length]);
  // Read new lines aloud with two voices, so the room hears the 911 agent work.
  useEffect(() => {
    if (!speak || !incident || typeof speechSynthesis === "undefined") return;
    const key = `${incident.id}:`;
    const done = spoken.current.startsWith(key) ? Number(spoken.current.slice(key.length)) : 0;
    const voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
    for (const line of lines.slice(done)) {
      if (line.who === "system") continue;
      const u = new SpeechSynthesisUtterance(line.text);
      u.rate = 1.08;
      u.pitch = line.who === "ai" ? 1.1 : 0.85;
      if (voices.length > 1) u.voice = line.who === "ai" ? voices[0] : voices[Math.min(3, voices.length - 1)];
      speechSynthesis.speak(u);
    }
    spoken.current = `${key}${lines.length}`;
  }, [lines, speak, incident]);

  if (!incident) return null;
  return (
    <div ref={box} className="flex max-h-[320px] flex-col gap-2 overflow-y-auto pr-1">
      {lines.map((l, i) =>
        l.who === "system" ? (
          <div key={i} className="py-1 text-center text-[0.68rem] font-extrabold uppercase tracking-wider text-faint">{l.text}</div>
        ) : (
          <div key={i} className={cx("flex", l.who === "ai" ? "justify-end" : "justify-start")}>
            <div className={cx("max-w-[85%] rounded-2xl px-4 py-2.5 text-[0.92rem] font-semibold leading-snug",
              l.who === "ai" ? "rounded-br-md bg-accent text-white" : "rounded-bl-md bg-panel-2 text-text")}>
              <div className={cx("mb-0.5 text-[0.62rem] font-black uppercase tracking-wider", l.who === "ai" ? "text-white/75" : "text-faint")}>
                {l.who === "ai" ? "Within Reach AI" : "911 dispatcher (simulated)"}
              </div>
              {l.text}
            </div>
          </div>
        ),
      )}
    </div>
  );
}

export function LiveConsole() {
  const { state, link, skewMs } = useSosState();
  const now = useNow();
  const camLoc = useCameraLocation(state);
  const [mode, setMode] = useState<ClickMode>("none");
  const [speak, setSpeak] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const incident = state?.incident ?? null;
  const open = Boolean(incident && OPEN.includes(incident.status));
  const camera = state?.cameras.find((c) => c.id === CAMERA_ID) ?? state?.cameras[0] ?? null;
  const responder = incident?.responder_id ? state?.responders.find((r) => r.id === incident.responder_id) ?? null : null;
  const serverNow = now + skewMs;
  const available = useMemo(() => (state?.responders ?? []).filter((r) => r.available), [state]);
  const callOn = open && incident?.call.status !== "ended";

  useEffect(() => {
    setAgentWords(agentWords(incident, responder?.name ?? null));
  }, [incident, responder?.name]);

  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const [enabling, setEnabling] = useState<string | null>(null);
  const enableTexts = async (id: string) => {
    setEnabling(id);
    await act(() => sosCall("POST", `/sos/responders/${encodeURIComponent(id)}/texts`));
    setEnabling(null);
  };

  const onPick = (lat: number, lng: number) => {
    if (mode === "none") {
      if (!camera) void act(() => sosCall("PUT", `/sos/cameras/${encodeURIComponent(CAMERA_ID)}`, { lat, lng }));
      return;
    }
    const m = mode;
    setMode("none");
    if (m === "fire") void act(() => sosCall("POST", "/sos/fire", { lat, lng, camera_id: CAMERA_ID }));
    else void act(() => sosCall("POST", "/sos/places", { kind: m, lat, lng }));
  };

  let headline = "All clear";
  let sub = "Watching the camera. A fall or fire alerts the closest responder within a second.";
  if (incident && open) {
    const pending = incident.offers.find((o) => o.status === "sent");
    if (incident.status === "alerting" && pending) {
      headline = `Alerting ${pending.name}`;
      sub = `${pending.distance_m !== null ? `${pending.distance_m} m away · ` : ""}${Math.max(0, Math.ceil((pending.expires_at - serverNow) / 1000))}s to answer${pending.call === "rang" ? " · phone ringing" : ""}`;
    } else if (incident.status === "no_responders") {
      headline = "No one available yet";
      sub = "Waiting for a responder to come on call. 911 has been told.";
    } else if (incident.status === "en_route") {
      headline = `${responder?.name ?? "Responder"} is on the way`;
      sub = incident.plan ? `${incident.plan.total_m} m walk · route: ${incident.plan.legs.map((l) => (l.kind === "person" ? "person" : l.kind === "aed" ? "AED" : "extinguisher")).join(" → ")}` : "Working out the route...";
    } else if (incident.status === "on_scene") {
      headline = `${responder?.name ?? "Responder"} is with them`;
      sub = `Arrived ${incident.arrived_at ? ago(incident.arrived_at - incident.started_at) : ""} after the ${incident.kind === "fire" ? "fire" : "fall"}`;
    }
  }

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-black tracking-tight">Live</h1>
        <Pill tone={link === "live" ? "green" : link === "down" ? "red" : "grey"}>
          {link === "live" ? "Connected" : link === "down" ? `Can't reach ${agentUrl()}` : "Connecting"}
        </Pill>
        <Pill tone={available.length ? "green" : "orange"}>{available.length} on call</Pill>
        <Pill tone={state?.settings.texts ? "green" : "grey"}>{state?.settings.texts ? "Texts on" : "Texts off"}</Pill>
        <Pill tone={state?.settings.calls ? "green" : "grey"}>{state?.settings.calls ? "Calls on" : "Calls off"}</Pill>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void act(() => sosCall("POST", "/sos/simulate/fall", { camera_id: CAMERA_ID }))}>Simulate fall</Button>
          <Button size="sm" tone={mode === "fire" ? "decision" : "default"} onClick={() => setMode(mode === "fire" ? "none" : "fire")}>
            {mode === "fire" ? "Click the map" : "Report fire"}
          </Button>
          {open ? <Button size="sm" tone="ok" onClick={() => void act(() => sosCall("POST", "/sos/resolve"))}>Close incident</Button> : null}
          <Button size="sm" tone="ghost" onClick={() => void act(async () => {
            await sosCall("POST", "/sos/reset");
            await fetch(`${visionUrl()}/reset`, { method: "POST" }).catch(() => undefined);
          })}>Reset</Button>
        </div>
      </div>
      {err ? <div className="rounded-2xl bg-accent/10 px-4 py-3 text-sm font-bold text-accent">{err}</div> : null}
      {camLoc.status ? <div className="rounded-2xl bg-decision/12 px-4 py-3 text-sm font-bold text-[#c26600]">{camLoc.status}</div> : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <CameraFeed alarm={open} />
          <Panel
            title="Map"
            right={
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" tone={mode === "aed" ? "ok" : "ghost"} onClick={() => setMode(mode === "aed" ? "none" : "aed")}>+ AED</Button>
                <Button size="sm" tone={mode === "extinguisher" ? "decision" : "ghost"} onClick={() => setMode(mode === "extinguisher" ? "none" : "extinguisher")}>+ Extinguisher</Button>
                <Button size="sm" tone="ghost" onClick={camLoc.register}>Locate camera</Button>
              </div>
            }
          >
            <div className="h-[380px] overflow-hidden rounded-xl">
              <LiveMap cameras={state?.cameras ?? []} responders={state?.responders ?? []} incident={incident}
                pinned={state?.pinned_places ?? []} mode={mode} onPick={onPick} />
            </div>
            <p className="pt-3 text-xs font-semibold text-muted">
              {mode !== "none" ? "Click the map to place it. " : ""}
              AEDs and extinguishers come from OpenStreetMap
              {state?.camera_places ? ` (${state.camera_places.count} near the camera)` : ""}. Add missing ones with the buttons above.
            </p>
          </Panel>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <section className={cx("overflow-hidden rounded-2xl border-2 bg-panel", open ? "border-accent/40" : "border-line")}>
            <div className="aspect-[1344/620] w-full">
              <AiLightsCard />
            </div>
            <div className="flex flex-col gap-4 p-5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className={cx("text-2xl font-black leading-tight", open ? "text-accent" : "text-text")}>{headline}</div>
                  <div className="mt-1 text-sm font-semibold text-muted">{sub}</div>
                </div>
                {incident && open ? <span className="num text-sm font-bold text-faint">{ago(serverNow - incident.started_at)}</span> : null}
              </div>
              {incident && open ? <Steps inc={incident} /> : null}
              {incident && open && incident.offers.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  {incident.offers.map((o) => (
                    <div key={o.id} className="flex items-center gap-2 rounded-xl bg-panel-2 px-3 py-2 text-sm font-bold">
                      <span>{o.name}</span>
                      {o.distance_m !== null ? <span className="text-muted">{o.distance_m} m</span> : null}
                      <span className={cx("ml-auto text-xs font-extrabold uppercase", o.status === "accepted" ? "text-ok-dark" : o.status === "sent" ? "text-decision" : "text-faint")}>
                        {o.status === "sent" ? "ringing" : o.status}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </section>

          <Panel
            title={<span className="flex items-center gap-2">911 call <span className="rounded-full bg-decision/12 px-2 py-0.5 text-[0.6rem] text-[#c26600]">Simulated</span></span>}
            right={<label className="flex cursor-pointer items-center gap-1.5 text-xs font-bold text-muted">
              <input type="checkbox" className="accent-[var(--accent)]" checked={speak} onChange={(e) => setSpeak(e.target.checked)} /> Read aloud
            </label>}
          >
            {callOn ? (
              <div className="mb-3 aspect-[1344/620] w-full overflow-hidden rounded-xl"><VoiceWaveCard /></div>
            ) : null}
            {incident ? <CallTranscript incident={incident} speak={speak} /> : (
              <div className="py-4 text-center text-sm font-semibold text-muted">The AI calls 911 the moment a fall or fire is seen. No real number is ever dialed.</div>
            )}
          </Panel>

          {incident ? (
            <Panel title="Timeline">
              <ol className="flex max-h-[220px] flex-col gap-2 overflow-y-auto text-sm font-semibold">
                {[...incident.timeline].reverse().map((t, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="num w-12 shrink-0 text-right text-faint">+{ago(t.at - incident.started_at)}</span>
                    <span>{t.text}</span>
                  </li>
                ))}
              </ol>
            </Panel>
          ) : null}

          <Panel title="Responders">
            {(state?.responders ?? []).length === 0 ? (
              <div className="text-sm font-semibold text-muted">No phones yet. Open Within Reach on a phone on the same Wi-Fi.</div>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {(state?.responders ?? []).map((r) => (
                  <li key={r.id} className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-3">
                      <span className={cx("flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-black text-white", r.available ? "bg-ok" : r.connected ? "bg-decision" : "bg-faint")}>
                        {r.name.slice(0, 1).toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-extrabold">{r.name}</div>
                        <div className="truncate text-xs font-semibold text-muted">
                          {!r.connected ? (r.callable ? "App closed · reachable by text" : "Offline")
                            : !r.on_duty ? "Off call" : r.lat === null ? "No location yet" : `On call · ±${Math.round(r.accuracy_m ?? 0)} m`}
                          {r.phone ? ` · ${r.phone}` : " · no number"}
                        </div>
                      </div>
                      {state?.settings.texts && r.phone && !r.text_line ? (
                        <Button size="sm" disabled={enabling === r.id} onClick={() => void enableTexts(r.id)}>
                          {enabling === r.id ? "Setting up..." : "Enable texts"}
                        </Button>
                      ) : null}
                      {r.text_line ? <Pill tone="green">Texts on</Pill> : null}
                    </div>
                    {r.text_line ? (
                      <div className="ml-12 rounded-xl bg-panel-2 px-3 py-2 text-xs font-semibold text-muted">
                        {r.name} texts <span className="num font-extrabold text-text">{r.text_line}</span> once from their phone, then alerts arrive as iMessages.
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
