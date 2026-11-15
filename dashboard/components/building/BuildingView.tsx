"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useEffectEvent, useMemo, useState } from "react";
import { useAppStatus } from "@/components/shell/AppStatus";
import { Badge, Button, EmptyState, Panel, Segmented } from "@/components/ui";
import { api } from "@/lib/api";
import { assetDisplayLabel, assetName, assetTitle, copy, hasAssetOfType, onlySimulatedOfType } from "@/lib/copy";
import { boundsOf, floorOf, floorsOf, hasScenario, indexCoverage, sweepZone, zoneCounts } from "@/lib/heatmap";
import { useBuilding } from "@/lib/hooks/useBuilding";
import { useThresholds } from "@/lib/hooks/useThresholds";
import { GAP_TYPES, isSimulated, nonCensusKind, type GapType } from "@/lib/rows";
import { formatMeasure } from "@/lib/thresholds";
import { CostarFacts, FlagsList, ScoreSummary } from "./BuildingFacts";
import { DocumentsTab } from "./DocumentsTab";
import { FixSummary } from "./FixSummary";
import { FloorHeatmap } from "./FloorHeatmap";
import { matterportAvailable } from "./MatterportTwin";
import { OutsidePanel } from "./OutsidePanel";
import { ZoneLegend } from "./ZoneLegend";

const MatterportTwin = dynamic(() => import("./MatterportTwin").then((m) => m.MatterportTwin), { ssr: false });

type Scenario = "current" | "proposed";
type Notice = { tone: "ok" | "err"; text: string } | null;

const FIX_WAIT_MS = 120000;

export function BuildingView({ id }: { id: string }) {
  const [type, setType] = useState<GapType>("aed");
  const [floorSel, setFloorSel] = useState<number | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [scenarioSel, setScenarioSel] = useState<Scenario>("current");
  const [request, setRequest] = useState<GapType | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState<"fix" | "rerun" | null>(null);
  const [view, setView] = useState<"2d" | "3d">("2d");
  const { health } = useAppStatus();
  const th = useThresholds();
  const t = th.thresholds;

  const index0 = useBuildingIndex(id, request);
  const { data, index } = index0;

  const fixType = type === "exit" ? null : type;
  const hasProposed = hasScenario(index, "proposed", type);
  const scenario: Scenario = scenarioSel === "proposed" && hasProposed ? "proposed" : "current";
  const proposedAsset = data.assets.find((a) => a.source === "proposed" && a.type === type);
  const fix =
    data.fixes.find((f) => f.asset_type === type && proposedAsset && f.sweep_id === proposedAsset.sweep_id) ??
    data.fixes.find((f) => f.asset_type === type) ??
    null;
  const waitingFor = request && !hasScenario(index, "proposed", request) ? request : null;

  const nodeById = useMemo(() => new Map(data.nodes.map((n) => [n.sweep_id, n])), [data.nodes]);
  const proposedNode = proposedAsset?.sweep_id ? nodeById.get(proposedAsset.sweep_id) : undefined;
  const rippleFrom =
    proposedAsset && typeof proposedAsset.x === "number" && typeof proposedAsset.z === "number"
      ? { x: proposedAsset.x, z: proposedAsset.z }
      : proposedNode && typeof proposedNode.x === "number" && typeof proposedNode.z === "number"
        ? { x: proposedNode.x, z: proposedNode.z }
        : null;
  const proposedFloor =
    typeof proposedAsset?.floor === "number" ? proposedAsset.floor : proposedNode ? floorOf(proposedNode) : null;

  const floors = useMemo(() => floorsOf(data.nodes), [data.nodes]);
  const floor =
    floorSel !== null && floors.includes(floorSel)
      ? floorSel
      : scenario === "proposed" && proposedFloor !== null && floors.includes(proposedFloor)
        ? proposedFloor
        : (floors[0] ?? 0);
  const bounds = useMemo(() => boundsOf(data.nodes), [data.nodes]);
  const counts = useMemo(
    () =>
      zoneCounts(
        data.nodes.filter((n) => n.sweep_id).map((n) => sweepZone(index, t, scenario, type, n.sweep_id as string)),
      ),
    [data.nodes, index, t, type, scenario],
  );
  const hoveredNode = hovered ? nodeById.get(hovered) : undefined;
  const mapped = data.coverage.some((c) => c.scenario === "current");
  // NULL time where the building has that equipment = not connected in the scan (CONTRACTS section 1).
  const unconnected = useMemo(() => {
    const out: Partial<Record<GapType, number>> = {};
    for (const g of GAP_TYPES) {
      if (!hasAssetOfType(data.assets, g)) continue;
      out[g] = data.coverage.filter((c) => c.scenario === "current" && c.asset_type === g && c.time_s === null).length;
    }
    return out;
  }, [data.assets, data.coverage]);
  const b = data.building;
  const kind = nonCensusKind(b);
  const simulated = useMemo(() => data.assets.filter((a) => a.source !== "proposed" && isSimulated(a)), [data.assets]);
  const simulatedLabels = [...new Set(simulated.map(assetDisplayLabel))];
  const apiDown = health.status === "unconfigured";
  const has3d = matterportAvailable(b?.matterport_model_id);
  const show3d = has3d && view === "3d";

  // The fast poll for a requested fix ends after FIX_WAIT_MS. If nothing arrived
  // by then, say so: the agent may be down.
  const onFixTimeout = useEffectEvent(() => {
    const missing = waitingFor;
    setRequest(null);
    if (missing) {
      setScenarioSel("current");
      setNotice({ tone: "err", text: `No ${assetName(missing)} placement arrived. Check the agent console.` });
    }
  });
  useEffect(() => {
    if (!request) return;
    const id = window.setTimeout(onFixTimeout, FIX_WAIT_MS);
    return () => window.clearTimeout(id);
  }, [request]);

  async function dropFix() {
    if (!fixType) return;
    setFloorSel(null);
    setScenarioSel("proposed");
    setNotice(null);
    if (hasProposed) return;
    setRequest(fixType);
    setBusy("fix");
    const res = await api.fixBuilding(id, { asset_type: fixType });
    setBusy(null);
    if (!res.ok) {
      setRequest(null);
      setScenarioSel("current");
      setNotice({ tone: "err", text: `Fix request failed: ${res.error}` });
    } else {
      data.refetchCensus();
    }
  }

  async function rerun() {
    setBusy("rerun");
    setNotice(null);
    const res = await api.rerunBuilding(id);
    setBusy(null);
    setNotice(
      res.ok
        ? { tone: "ok", text: "Rerun started. The agent console follows the new run." }
        : { tone: "err", text: `Rerun failed: ${res.error}` },
    );
  }

  if (!data.valid) {
    return (
      <div className="p-6">
        <EmptyState title="Building not found">The id in the address is not a building id.</EmptyState>
      </div>
    );
  }
  if (data.buildingStatus === "unconfigured") {
    return (
      <div className="p-6">
        <EmptyState title="--">{copy.supabaseMissing}</EmptyState>
      </div>
    );
  }
  if (data.buildingLoaded && !b) {
    return (
      <div className="p-6">
        <EmptyState title="Building not found">No buildings row with this id.</EmptyState>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <Link href="/" className="text-xs font-semibold text-muted hover:text-accent">
            City map
          </Link>
          <h1 className="mt-1 truncate text-3xl font-bold tracking-tight">{b?.name ?? "--"}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span>{b?.address ?? "--"}</span>
            {b?.city && <span>{b.city}</span>}
            {b?.property_type && <Badge tone="muted">{b.property_type}</Badge>}
            {kind === "fixture" && <Badge tone="warn">{copy.fixtureTag}</Badge>}
            {kind === "demo" && <Badge tone="warn">{copy.demoTag}</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {notice && (
            <span className={notice.tone === "ok" ? "text-sm text-ok" : "text-sm text-danger"}>{notice.text}</span>
          )}
          <Button onClick={rerun} disabled={busy !== null || apiDown} title={apiDown ? copy.agentMissing : undefined}>
            {busy === "rerun" ? "Starting" : "Rerun live"}
          </Button>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel
          title="Floor plan"
          right={
            <div className="flex flex-wrap items-center gap-2">
              {has3d && (
                <Segmented
                  size="sm"
                  value={view}
                  onChange={setView}
                  options={[
                    { value: "2d", label: "2D plan" },
                    { value: "3d", label: "3D twin" },
                  ]}
                />
              )}
              <Segmented
                size="sm"
                value={type}
                onChange={(v) => {
                  setType(v);
                  setFloorSel(null);
                }}
                options={GAP_TYPES.map((g) => ({ value: g, label: assetTitle(g) }))}
              />
              {floors.length > 1 && (
                <Segmented
                  size="sm"
                  value={String(floor)}
                  onChange={(v) => setFloorSel(Number(v))}
                  options={floors.map((f) => ({ value: String(f), label: `Floor ${f}` }))}
                />
              )}
              <Segmented
                size="sm"
                value={scenario}
                onChange={(v) => {
                  setFloorSel(null);
                  setScenarioSel(v);
                }}
                options={[
                  { value: "current", label: "Current" },
                  { value: "proposed", label: "With fix", disabled: !hasProposed },
                ]}
              />
            </div>
          }
          bodyClassName="p-0"
        >
          {simulated.length > 0 && (
            <div
              role="note"
              className="flex items-start gap-3 border-b border-warn/40 bg-warn/10 px-4 py-2.5 text-sm text-warn"
            >
              <span className="mt-0.5 inline-block h-3.5 w-5 shrink-0 rounded-sm border-2 border-dashed border-warn" aria-hidden />
              <span>
                <span className="font-semibold">{copy.simulatedNotice}</span>{" "}
                <span className="text-warn/80">{copy.simulatedPresent(simulatedLabels)}</span>
              </span>
            </div>
          )}
          {!data.nodesLoaded ? (
            <div className="p-4">
              <EmptyState title="Loading the scan graph" />
            </div>
          ) : !bounds ? (
            <div className="p-4">
              <EmptyState title="No sweeps with positions">
                twin_nodes has no rows with x and z for this building.
              </EmptyState>
            </div>
          ) : (
            <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="relative border-line p-3 lg:border-r">
                {show3d ? (
                  <MatterportTwin
                    modelId={b?.matterport_model_id ?? null}
                    assets={data.assets}
                    nodes={data.nodes}
                    showProposed={scenario === "proposed"}
                  />
                ) : (
                  <FloorHeatmap
                    nodes={data.nodes}
                    assets={data.assets}
                    index={index}
                    thresholds={t}
                    bounds={bounds}
                    floor={floor}
                    type={type}
                    scenario={scenario}
                    rippleFrom={rippleFrom}
                    hovered={hovered}
                    onHover={setHovered}
                  />
                )}
                {fixType && (
                  <div className="absolute right-4 bottom-4 flex items-center gap-3">
                    {waitingFor && (
                      <span className="rounded bg-panel/90 px-2 py-1 text-sm text-accent">
                        Fixer is placing a new {assetName(waitingFor)}
                      </span>
                    )}
                    {scenario === "current" ? (
                      <Button
                        tone="primary"
                        size="lg"
                        onClick={dropFix}
                        disabled={busy === "fix" || Boolean(waitingFor) || (!hasProposed && apiDown)}
                      >
                        Drop {assetTitle(fixType)}
                      </Button>
                    ) : (
                      <Button size="lg" onClick={() => setScenarioSel("current")}>
                        Show current
                      </Button>
                    )}
                  </div>
                )}
              </div>
              <div className="space-y-4 p-4">
                <ZoneLegend
                  type={type}
                  thresholds={th}
                  counts={mapped ? counts : null}
                  hasAsset={hasAssetOfType(data.assets, type)}
                  onlySimulated={onlySimulatedOfType(data.assets, type)}
                  simulatedLabels={simulatedLabels}
                />
                <div className="rounded-md border border-line bg-panel-2 p-3 text-sm">
                  <div className="label mb-1">Position</div>
                  {hoveredNode ? (
                    <>
                      <div className="font-semibold">
                        {hoveredNode.label || hoveredNode.room_type || hoveredNode.sweep_id}
                      </div>
                      <div className="text-muted">
                        Floor {floorOf(hoveredNode)}
                        {hoveredNode.is_stairs ? ", stairs" : ""}
                        {hoveredNode.is_elevator ? ", elevator" : ""}
                      </div>
                      <div className="num mt-1">
                        {index.has(`${scenario}|${type}|${hoveredNode.sweep_id}`)
                          ? formatMeasure(type, index.get(`${scenario}|${type}|${hoveredNode.sweep_id}`) ?? null, t)
                          : copy.notMapped}
                      </div>
                    </>
                  ) : (
                    <div className="text-muted">Hover a position on the plan.</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          <FixSummary fix={fix} type={type} thresholds={t} nodes={data.nodes} unconnected={unconnected[type]} />
          <ScoreSummary score={data.score} thresholds={t} selected={type} unconnected={unconnected} />
          <FlagsList score={data.score} assets={data.assets} mapped={mapped} />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <DocumentsTab documents={data.documents} loaded={data.documentsLoaded} />
        <div className="space-y-4">
          <OutsidePanel building={b} />
          <CostarFacts building={b} />
        </div>
      </div>
    </div>
  );
}

function useBuildingIndex(id: string, request: GapType | null) {
  const data = useBuilding(id, { waiting: request !== null });
  const index = useMemo(() => indexCoverage(data.coverage), [data.coverage]);
  return { data, index };
}
