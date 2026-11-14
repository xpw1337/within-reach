"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, EmptyState, Panel, Segmented } from "@/components/ui";
import { assetTitle, copy } from "@/lib/copy";
import { boundsOf, floorOf, floorsOf, indexCoverage, sweepZone, zoneCounts } from "@/lib/heatmap";
import { useBuilding } from "@/lib/hooks/useBuilding";
import { useThresholds } from "@/lib/hooks/useThresholds";
import { GAP_TYPES, isFixture, type GapType } from "@/lib/rows";
import { formatMeasure } from "@/lib/thresholds";
import { CostarFacts, FlagsList, ScoreSummary } from "./BuildingFacts";
import { FloorHeatmap } from "./FloorHeatmap";
import { ZoneLegend } from "./ZoneLegend";

export function BuildingView({ id }: { id: string }) {
  const [type, setType] = useState<GapType>("aed");
  const [floorSel, setFloorSel] = useState<number | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const data = useBuilding(id);
  const th = useThresholds();
  const t = th.thresholds;
  const scenario = "current" as const;

  const floors = useMemo(() => floorsOf(data.nodes), [data.nodes]);
  const floor = floorSel !== null && floors.includes(floorSel) ? floorSel : (floors[0] ?? 0);
  const bounds = useMemo(() => boundsOf(data.nodes), [data.nodes]);
  const index = useMemo(() => indexCoverage(data.coverage), [data.coverage]);
  const counts = useMemo(
    () =>
      zoneCounts(
        data.nodes.filter((n) => n.sweep_id).map((n) => sweepZone(index, t, scenario, type, n.sweep_id as string)),
      ),
    [data.nodes, index, t, type],
  );
  const hoveredNode = hovered ? data.nodes.find((n) => n.sweep_id === hovered) : undefined;
  const mapped = data.coverage.some((c) => c.scenario === "current");
  const b = data.building;

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
            {isFixture(b) && <Badge tone="warn">{copy.fixtureTag}</Badge>}
          </div>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel
          title="Floor plan"
          right={
            <div className="flex flex-wrap items-center gap-2">
              <Segmented
                size="sm"
                value={type}
                onChange={setType}
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
            </div>
          }
          bodyClassName="p-0"
        >
          {!data.nodesLoaded ? (
            <div className="p-4">
              <EmptyState title="Loading the scan graph" />
            </div>
          ) : !bounds ? (
            <div className="p-4">
              <EmptyState title="No sweeps with positions">twin_nodes has no rows with x and z for this building.</EmptyState>
            </div>
          ) : (
            <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="border-line p-3 lg:border-r">
                <FloorHeatmap
                  nodes={data.nodes}
                  assets={data.assets}
                  index={index}
                  thresholds={t}
                  bounds={bounds}
                  floor={floor}
                  type={type}
                  scenario={scenario}
                  hovered={hovered}
                  onHover={setHovered}
                />
              </div>
              <div className="space-y-4 p-4">
                <ZoneLegend type={type} thresholds={th} counts={mapped ? counts : null} />
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
          <ScoreSummary score={data.score} thresholds={t} selected={type} />
          <FlagsList score={data.score} assets={data.assets} mapped={mapped} />
          <CostarFacts building={b} />
        </div>
      </div>
    </div>
  );
}
