"use client";

import Link from "next/link";
import { useState } from "react";
import { useAppStatus } from "@/components/shell/AppStatus";
import { Badge, Button, cx, EmptyState, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { readEmsBriefed, readEmsDoor, readVerification } from "@/lib/contracts";
import { assetDisplayLabel, copy, EMPTY, roleLabel } from "@/lib/copy";
import { clock, humanize, offset, secondsBetween } from "@/lib/format";
import {
  confirmState,
  describeEvent,
  fall911Timer,
  incidentTitle,
  latencies,
  latestRouteSpeak,
  originOf,
} from "@/lib/incident";
import { useBuilding } from "@/lib/hooks/useBuilding";
import { isOpen, useLive } from "@/lib/hooks/useLive";
import { useNow } from "@/lib/hooks/useNow";
import { isSimulated, type Camera, type Dispatch, type Incident, type IncidentEvent, type Responder } from "@/lib/rows";
import { RouteFlythrough } from "./RouteFlythrough";

const DESK = "desk";

function useCommand() {
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function run(name: string, fn: () => Promise<{ ok: boolean; error?: string }>) {
    setBusy(name);
    setMsg(null);
    const res = await fn();
    setBusy(null);
    if (!res.ok) setMsg({ ok: false, text: `${humanize(name)} failed: ${"error" in res ? res.error : ""}` });
  }
  return { busy, msg, run };
}

function Countdown({ deadline, now }: { deadline: string | null; now: number | null }) {
  if (!deadline || now === null) return <span className="num">{EMPTY}</span>;
  const s = Math.max(0, Math.ceil((Date.parse(deadline) - now) / 1000));
  return <span className="num">{s} s</span>;
}

function ConfirmBar({ incident, events, cmd }: { incident: Incident; events: IncidentEvent[]; cmd: ReturnType<typeof useCommand> }) {
  const state = confirmState(incident, events);
  const fall = fall911Timer(incident, events);
  const now = useNow(250, state.pending || Boolean(fall));
  if (!state.pending && !fall) return null;
  if (fall && !state.pending) {
    return (
      <div className="flex flex-wrap items-center gap-4 rounded-lg border-2 border-zone-yellow bg-zone-yellow/10 px-5 py-4">
        <div className="text-lg font-bold">
          911 briefing in <Countdown deadline={fall.firesAt} now={now} /> unless staff cancel
        </div>
        <Button
          size="lg"
          className="ml-auto"
          disabled={cmd.busy !== null}
          onClick={() => cmd.run("cancel_911", () => api.cancel911(incident.id, DESK))}
        >
          Cancel 911 briefing
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg border-2 border-decision bg-decision/10 px-5 py-4">
      <div>
        <div className="text-xl font-bold">Confirm before responders and the 911 briefing go out</div>
        <div className="mt-0.5 text-sm text-muted">
          {state.mode === "auto" ? (
            <>
              Witnessed collapse: auto-proceeds in <Countdown deadline={state.deadline} now={now} />
            </>
          ) : state.mode === "escalate" ? (
            <>
              Found down: 911 briefing only (no responders) in <Countdown deadline={state.deadline} now={now} />
            </>
          ) : (
            "Waiting for the desk."
          )}
        </div>
      </div>
      <div className="ml-auto flex gap-3">
        <Button
          tone="danger"
          size="lg"
          disabled={cmd.busy !== null}
          onClick={() => cmd.run("confirm", () => api.confirmIncident(incident.id, "confirm", DESK))}
          className="min-w-44 text-lg"
        >
          CONFIRM
        </Button>
        <Button
          size="lg"
          disabled={cmd.busy !== null}
          onClick={() => cmd.run("false_alarm", () => api.confirmIncident(incident.id, "false_alarm", DESK))}
          className="min-w-44 text-lg"
        >
          FALSE ALARM
        </Button>
      </div>
    </div>
  );
}

function IncidentCard({
  incident,
  camera,
  buildingId,
  buildingName,
}: {
  incident: Incident;
  camera: Camera | null;
  buildingId: string | null;
  buildingName: string | null;
}) {
  const v = readVerification(incident.verification);
  const open = isOpen(incident);
  return (
    <Panel
      title="Incident"
      right={<Badge tone={open ? "red" : "muted"}>{humanize(incident.status)}</Badge>}
      className={open ? "border-zone-red/50" : undefined}
    >
      <div className="flex gap-5">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="text-3xl font-bold tracking-tight">{incidentTitle(incident)}</div>
          <div className="text-base">
            {camera?.landmark ? `By ${camera.landmark}` : EMPTY}
            {buildingName ? (
              <span className="text-muted">
                ,{" "}
                {buildingId ? (
                  <Link href={`/building/${buildingId}`} className="underline decoration-dotted hover:text-accent">
                    {buildingName}
                  </Link>
                ) : (
                  buildingName
                )}
              </span>
            ) : null}
            {camera?.floor !== null && camera?.floor !== undefined ? <span className="text-muted">, floor {camera.floor}</span> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={incident.witnessed ? "red" : "yellow"}>
              {incident.witnessed === null ? "witnessed: --" : incident.witnessed ? "witnessed collapse" : "found down"}
            </Badge>
            {(incident.modifiers ?? []).map((m) => (
              <Badge key={m} tone="decision">
                + {humanize(m)}
              </Badge>
            ))}
            {incident.scene_safe === false && <Badge tone="red">scene unsafe</Badge>}
            {(incident.hazards ?? []).map((h) => (
              <Badge key={h} tone="warn">
                {humanize(h)}
              </Badge>
            ))}
          </div>
          {incident.scene_safe === false && (
            <p className="text-sm text-zone-red">Bystanders told to stay back; police notified; no responders sent in.</p>
          )}
          {v?.isEmergency === false && (
            <p className="text-sm text-muted">Scene check suggests this may not be an emergency. Advice only: the desk decides.</p>
          )}
          <div className="text-xs text-muted">
            Camera {incident.camera_id ?? EMPTY}, detected {clock(incident.created_at)}
          </div>
        </div>
        {incident.snapshot_url && (
          // The single incident frame (CONTRACTS section 5).
          // eslint-disable-next-line @next/next/no-img-element
          <img src={incident.snapshot_url} alt="Incident snapshot" className="h-40 w-auto rounded-md border border-line object-cover" />
        )}
      </div>
    </Panel>
  );
}

function LatencyMetrics({ incident, dispatches }: { incident: Incident; dispatches: Dispatch[] }) {
  const rows = latencies(incident, dispatches);
  const origin = originOf(incident);
  return (
    <Panel title="Latency" right={<span className="text-xs text-muted">seconds {origin.label}</span>}>
      <div className="grid grid-cols-2 gap-x-5 gap-y-4">
        {rows.map((r, i) => (
          <Stat
            key={r.key}
            label={r.label}
            value={r.seconds !== null ? r.seconds.toFixed(1) : null}
            unit="s"
            size={i < 2 ? "lg" : "sm"}
            tone={i === 0 ? "accent" : undefined}
          />
        ))}
      </div>
      {!incident.collapse_at && <p className="mt-3 text-xs text-muted">{copy.foundDownTimeUnknown}.</p>}
    </Panel>
  );
}

function Timeline({ incident, events, who }: { incident: Incident; events: IncidentEvent[]; who: (a: string | null) => string }) {
  const o = originOf(incident).ts;
  return (
    <Panel title="Timeline" className="flex min-h-0 flex-col" bodyClassName="max-h-[560px] overflow-y-auto p-0">
      {events.length === 0 ? (
        <div className="p-4 text-sm text-muted">No events yet.</div>
      ) : (
        <ol>
          {events.map((e) => (
            <li key={e.id} className={cx("flash-in flex gap-3 border-b border-line/70 px-4 py-2", e.kind === "speak" && "bg-accent/[0.05]")}>
              <span className="num w-16 shrink-0 text-right text-xs text-muted">{offset(secondsBetween(o, e.ts))}</span>
              <span className="w-20 shrink-0 truncate text-[0.7rem] font-bold uppercase tracking-wider text-faint">
                {e.actor?.startsWith("responder:") ? "responder" : (e.actor ?? EMPTY)}
              </span>
              <span className="min-w-0 text-sm leading-snug">{describeEvent(e, who)}</span>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

const ROLE_TONE: Record<string, "red" | "accent" | "yellow" | "muted"> = {
  patient: "red",
  aed_runner: "accent",
  staff: "yellow",
  broadcast: "muted",
};

function ResponderList({ dispatches, responders, incident }: { dispatches: Dispatch[]; responders: Responder[]; incident: Incident }) {
  const byId = new Map(responders.map((r) => [r.id, r]));
  const o = originOf(incident).ts;
  return (
    <Panel title="Responders">
      {dispatches.length === 0 ? (
        <p className="text-sm text-muted">No alerts sent yet.</p>
      ) : (
        <ul className="space-y-2">
          {dispatches.map((d) => {
            const r = d.responder_id ? byId.get(d.responder_id) : undefined;
            return (
              <li key={d.id} className="flex items-center gap-3 rounded-md border border-line bg-panel-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{r?.name ?? "Responder"}</div>
                  <div className="text-xs text-muted">
                    {humanize(r?.role)}
                    {r?.cpr_trained ? ", CPR trained" : ""}, wave {d.wave ?? EMPTY}, {humanize(d.channel)}
                  </div>
                </div>
                {d.role && <Badge tone={ROLE_TONE[d.role] ?? "muted"}>{roleLabel(d.role)}</Badge>}
                <span className="w-24 text-right">
                  <span
                    className={cx(
                      "block text-sm font-semibold",
                      d.status === "accepted" || d.status === "arrived" ? "text-ok" : d.status === "sent" ? "text-zone-yellow" : "text-muted",
                    )}
                  >
                    {humanize(d.status)}
                  </span>
                  <span className="num block text-[0.7rem] text-muted">{offset(secondsBetween(o, d.responded_at ?? d.sent_at))}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function EmsDoorPanel({
  buildingDoor,
  events,
  simulatedLabels,
}: {
  buildingDoor: unknown;
  events: IncidentEvent[];
  /** Demo props placed by the team in this building, named wherever the briefing may mention them. */
  simulatedLabels: string[];
}) {
  const briefed = [...events].reverse().find((e) => e.kind === "ems_briefed");
  const b = briefed ? readEmsBriefed(briefed.payload) : null;
  const door = readEmsDoor(buildingDoor as never);
  return (
    <Panel title="EMS door">
      <div className="text-xl font-bold">{b?.emsDoor?.desc ?? door?.desc ?? EMPTY}</div>
      {door?.reason && <p className="mt-1 text-sm text-muted">{door.reason}</p>}
      {(door?.staging || door?.hydrant) && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="label">Staging</div>
            <div>{door?.staging ?? EMPTY}</div>
          </div>
          <div>
            <div className="label">Nearest hydrant</div>
            <div>{door?.hydrant ?? EMPTY}</div>
          </div>
        </div>
      )}
      {b?.briefingText && (
        <div className="mt-3 rounded-md border border-line bg-panel-2 p-3 text-sm leading-relaxed">
          <div className="label mb-1">911 briefing</div>
          {b.briefingText}
        </div>
      )}
      {simulatedLabels.map((l) => (
        <div key={l} className="mt-3 flex items-start gap-2 text-xs text-warn">
          <span className="mt-0.5 inline-block h-3 w-4 shrink-0 rounded-sm border-2 border-dashed border-warn" aria-hidden />
          <span>
            <span className="font-semibold">{l}</span>: {copy.simulatedNotCensus}
          </span>
        </div>
      ))}
    </Panel>
  );
}

function HandoffCard({ incident }: { incident: Incident }) {
  const o = originOf(incident).ts;
  const rel = (ts: string | null) => (ts ? `${clock(ts)} (${offset(secondsBetween(o, ts))})` : EMPTY);
  const rows: [string, string][] = [
    ["Collapse", incident.collapse_at ? clock(incident.collapse_at) : copy.foundDownTimeUnknown],
    ["Witnessed", incident.witnessed === null ? EMPTY : incident.witnessed ? "Yes" : "No"],
    ["First instruction", rel(incident.first_instruction_at)],
    ["911 notified", rel(incident.ems_notified_at)],
    ["Responder accepted", rel(incident.first_accept_at)],
    ["Responder arrived", rel(incident.responder_arrived_at)],
    ["CPR started", rel(incident.cpr_started_at)],
    ["AED arrived", rel(incident.aed_arrived_at)],
    ["Modifiers", (incident.modifiers ?? []).map(humanize).join(", ") || "none"],
  ];
  return (
    <Panel title="Handoff card (Utstein-style)" right={<Badge tone={incident.status === "resolved" ? "green" : "muted"}>{incident.status === "resolved" ? "final" : "live"}</Badge>}>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-line/60 py-1.5 last:border-b-0">
            <dt className="text-sm text-muted">{k}</dt>
            <dd className="num text-right text-sm">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function Controls({ incident, cmd }: { incident: Incident | null; cmd: ReturnType<typeof useCommand> }) {
  const [armReset, setArmReset] = useState(false);
  const { health } = useAppStatus();
  const off = health.status === "unconfigured";
  const open = isOpen(incident);
  return (
    <div className="flex flex-wrap items-center gap-2">
      {open && incident && (
        <>
          <Button size="sm" disabled={cmd.busy !== null || Boolean(incident.cpr_started_at)} onClick={() => cmd.run("milestone", () => api.milestone(incident.id, "cpr_started", DESK))}>
            CPR started
          </Button>
          <Button size="sm" disabled={cmd.busy !== null || Boolean(incident.aed_arrived_at)} onClick={() => cmd.run("milestone", () => api.milestone(incident.id, "aed_arrived", DESK))}>
            AED arrived
          </Button>
          <Button size="sm" disabled={cmd.busy !== null || Boolean(incident.responder_arrived_at)} onClick={() => cmd.run("milestone", () => api.milestone(incident.id, "responder_arrived", DESK))}>
            Responder arrived
          </Button>
          <Button size="sm" tone="ok" disabled={cmd.busy !== null} onClick={() => cmd.run("resolve", () => api.resolveIncident(incident.id, DESK))}>
            Resolve
          </Button>
          {/* With REQUIRE_CONFIRM=false there is no confirm bar, so the desk's way to stop a false trigger lives here. */}
          <Button size="sm" disabled={cmd.busy !== null} onClick={() => cmd.run("false_alarm", () => api.confirmIncident(incident.id, "false_alarm", DESK))}>
            False alarm
          </Button>
          <span className="mx-1 h-6 w-px bg-line" />
        </>
      )}
      <span className="label mr-1">Simulate</span>
      <Button size="sm" disabled={off || cmd.busy !== null} onClick={() => cmd.run("simulate", () => api.simulate("cardiac"))}>
        Cardiac
      </Button>
      <Button size="sm" disabled={off || cmd.busy !== null} onClick={() => cmd.run("simulate", () => api.simulate("fall"))}>
        Fall
      </Button>
      <Button size="sm" disabled={off || cmd.busy !== null} title="Stretch goal" onClick={() => cmd.run("simulate", () => api.simulate("outdoor"))}>
        Outdoor
      </Button>
      <Button
        size="sm"
        tone={armReset ? "danger" : "ghost"}
        disabled={off || cmd.busy !== null}
        onBlur={() => setArmReset(false)}
        onClick={() => {
          if (!armReset) {
            setArmReset(true);
            return;
          }
          setArmReset(false);
          void cmd.run("reset", () => api.reset());
        }}
      >
        {armReset ? "Click again to reset" : "Reset"}
      </Button>
    </div>
  );
}

export function LiveView() {
  const live = useLive();
  const cmd = useCommand();
  const i = live.current;
  const camera = live.cameras.find((c) => c.id === i?.camera_id) ?? null;
  const buildingId = i?.building_id ?? camera?.building_id ?? null;
  const building = useBuilding(buildingId ?? "");
  const speak = latestRouteSpeak(live.events);
  const simulatedLabels = [
    ...new Set(building.assets.filter((a) => a.source !== "proposed" && isSimulated(a)).map(assetDisplayLabel)),
  ];
  const nameOf = new Map(live.responders.map((r) => [r.id, r.name]));
  const who = (actor: string | null) => {
    if (!actor) return EMPTY;
    if (actor.startsWith("responder:")) return nameOf.get(actor.slice("responder:".length)) ?? "a responder";
    return actor;
  };

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Live</h1>
          <p className="text-sm text-muted">
            {live.cameras.length
              ? `Watching ${live.cameras.map((c) => `${c.id}${c.landmark ? ` (${c.landmark})` : ""}`).join(", ")}`
              : "No cameras seeded."}
          </p>
        </div>
        <Controls incident={i} cmd={cmd} />
      </header>
      {cmd.msg && <p className={cmd.msg.ok ? "text-sm text-ok" : "text-sm text-danger"}>{cmd.msg.text}</p>}

      {live.status === "unconfigured" ? (
        <EmptyState title={EMPTY}>{copy.supabaseMissing}</EmptyState>
      ) : !i ? (
        <EmptyState title="No incident">
          {live.loaded ? "Idle. A person-down event or a Simulate button opens an incident here." : "Connecting"}
        </EmptyState>
      ) : (
        <>
          {!isOpen(i) && (
            <div className="rounded-md border border-line bg-panel-2 px-4 py-2 text-sm text-muted">
              Showing the last incident ({humanize(i.status)}). No incident is open.
            </div>
          )}
          <ConfirmBar incident={i} events={live.events} cmd={cmd} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <IncidentCard incident={i} camera={camera} buildingId={buildingId} buildingName={building.building?.name ?? null} />
            <LatencyMetrics incident={i} dispatches={live.dispatches} />
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
            <RouteFlythrough camera={camera} routes={live.routes} speak={speak} buildingId={buildingId} />
            <Timeline incident={i} events={live.events} who={who} />
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <ResponderList dispatches={live.dispatches} responders={live.responders} incident={i} />
            <EmsDoorPanel
              buildingDoor={building.building?.ems_door ?? null}
              events={live.events}
              simulatedLabels={simulatedLabels}
            />
            <HandoffCard incident={i} />
          </div>
        </>
      )}
    </div>
  );
}
