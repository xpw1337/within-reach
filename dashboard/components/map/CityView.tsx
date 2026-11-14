"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useAppStatus } from "@/components/shell/AppStatus";
import { Badge, Button, cx, EmptyState, Panel, Segmented, Stat } from "@/components/ui";
import { api, type City } from "@/lib/api";
import { assetName, assetTitle, copy, EMPTY } from "@/lib/copy";
import { dateTime, int, pct, usd } from "@/lib/format";
import { useRealtimeTable } from "@/lib/hooks/useRealtimeTable";
import { useThresholds } from "@/lib/hooks/useThresholds";
import { GAP_TYPES, isFixture, type Building, type BuildingScore, type GapType } from "@/lib/rows";
import { selectAll } from "@/lib/supabase";
import { formatLimit, formatMeasure, measureName, type Thresholds } from "@/lib/thresholds";
import { redColor, type CityPoint } from "./CityMap";

const CityMap = dynamic(() => import("./CityMap").then((m) => m.CityMap), {
  ssr: false,
  loading: () => <div className="h-full min-h-[420px] w-full bg-panel-2" />,
});

const CITIES: { value: City; label: string; center: [number, number] }[] = [
  { value: "Houston", label: "Houston", center: [29.7604, -95.3698] },
  { value: "Los Angeles", label: "Los Angeles", center: [34.0522, -118.2437] },
];

type MapBuilding = Pick<Building, "id" | "name" | "city" | "lat" | "lng" | "costar_property_id" | "property_type">;

function gapOf(s: BuildingScore, g: GapType) {
  if (g === "aed") return { worst: s.aed_worst_s, red: s.aed_red_frac };
  if (g === "extinguisher") return { worst: s.ext_worst_s, red: s.ext_red_frac };
  return { worst: s.exit_worst_s, red: s.exit_red_frac };
}

function sameCity(a: string | null, b: City) {
  return (a ?? "").trim().toLowerCase() === b.toLowerCase();
}

function headline(g: GapType, t: Thresholds | null) {
  const limit = t ? `more than ${formatLimit(g, t)}` : `beyond the ${measureName(g)} limit`;
  const from = g === "exit" ? "an exit" : g === "aed" ? "any AED" : "an extinguisher";
  return `have a spot ${limit} from ${from} ${copy.visibleInScan}`;
}

export function CityView() {
  const router = useRouter();
  const [city, setCity] = useState<City>("Houston");
  const [gap, setGap] = useState<GapType>("aed");
  const [stopping, setStopping] = useState(false);
  const [stopMsg, setStopMsg] = useState<string | null>(null);
  const { latestRun, health } = useAppStatus();
  const th = useThresholds();
  const t = th.thresholds;

  const buildings = useRealtimeTable<MapBuilding>({
    key: "city",
    table: "buildings",
    realtime: false,
    pollMs: latestRun?.status === "running" ? 30000 : undefined,
    load: (db) =>
      selectAll<MapBuilding>((from, to) =>
        db
          .from("buildings")
          .select("id,name,city,lat,lng,costar_property_id,property_type")
          .order("id")
          .range(from, to),
      ),
    rowKey: (b) => b.id,
  });
  const scores = useRealtimeTable<BuildingScore>({
    key: "city",
    table: "building_scores",
    load: (db) =>
      selectAll<BuildingScore>((from, to) => db.from("building_scores").select("*").order("building_id").range(from, to)),
    rowKey: (s) => s.building_id,
  });

  const byId = useMemo(() => new Map(buildings.rows.map((b) => [b.id, b])), [buildings.rows]);

  const scored = useMemo(
    () =>
      scores.rows
        .map((s) => ({ s, b: byId.get(s.building_id) }))
        .filter((x): x is { s: BuildingScore; b: MapBuilding } => Boolean(x.b && sameCity(x.b.city, city))),
    [scores.rows, byId, city],
  );
  const counted = scored.filter((x) => !isFixture(x.b));
  const allCounted = scores.rows.filter((s) => {
    const b = byId.get(s.building_id);
    return b && !isFixture(b);
  }).length;

  const withGap = counted.filter((x) => {
    const r = gapOf(x.s, gap).red;
    return typeof r === "number" && r > 0;
  }).length;
  const measuredForGap = counted.filter((x) => typeof gapOf(x.s, gap).red === "number").length;
  const share = measuredForGap > 0 ? withGap / measuredForGap : null;
  const peopleAtRisk = counted.reduce((sum, x) => sum + (x.s.people_at_risk ?? 0), 0);
  const anyPeople = counted.some((x) => x.s.people_at_risk !== null);

  const points: CityPoint[] = useMemo(
    () =>
      scored
        .filter((x) => typeof x.b.lat === "number" && typeof x.b.lng === "number")
        .map((x) => {
          const g = gapOf(x.s, gap);
          return {
            id: x.b.id,
            lat: x.b.lat as number,
            lng: x.b.lng as number,
            red: g.red,
            label: `${x.b.name ?? "Building"}: ${pct(g.red)} red (${assetName(gap)})`,
          };
        }),
    [scored, gap],
  );

  const ranked = useMemo(
    () =>
      [...scored].sort((a, b) => {
        const ra = a.s.rank ?? Number.POSITIVE_INFINITY;
        const rb = b.s.rank ?? Number.POSITIVE_INFINITY;
        if (ra !== rb) return ra - rb;
        return (b.s.gap_score ?? -1) - (a.s.gap_score ?? -1);
      }),
    [scored],
  );

  const cityInfo = CITIES.find((c) => c.value === city) ?? CITIES[0];
  const run = latestRun;
  const runFrac =
    run && run.buildings_target && run.buildings_target > 0
      ? Math.min(1, (run.buildings_done ?? 0) / run.buildings_target)
      : null;

  async function stopRun() {
    if (!run) return;
    setStopping(true);
    const res = await api.stopRun(run.id);
    setStopping(false);
    setStopMsg(res.ok ? "Stopping after the current building." : `Stop failed: ${res.error}`);
  }

  const unconfigured = scores.status === "unconfigured";

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={city} onChange={setCity} options={CITIES.map((c) => ({ value: c.value, label: c.label }))} />
        <Segmented value={gap} onChange={setGap} options={GAP_TYPES.map((g) => ({ value: g, label: assetTitle(g) }))} />
        <span className="text-xs text-muted">
          Markers colored by the share {copy.redShareOfPositions} beyond the {assetName(gap)} limit.
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title={`Headline, ${city}`} bodyClassName="p-5">
          <div className="flex items-end gap-5">
            <div
              className={cx(
                "num shrink-0 text-7xl leading-none font-bold whitespace-nowrap",
                share === null ? "text-faint" : "text-zone-red",
              )}
            >
              {share === null ? EMPTY : pct(share)}
            </div>
            <div className="pb-1 text-lg leading-snug">
              of buildings measured {headline(gap, t)}
              <div className="mt-1 text-sm text-muted">
                <span className="num text-text">{measuredForGap ? `${int(withGap)} of ${int(measuredForGap)}` : EMPTY}</span>{" "}
                buildings in {city}. {th.status !== "ok" && copy.approximationShort + " unavailable."}
              </div>
            </div>
          </div>
          <div className="mt-5 grid grid-cols-3 gap-4 border-t border-line pt-4">
            <Stat label={`Measured in ${city}`} value={counted.length ? int(counted.length) : null} size="sm" />
            <Stat label="Measured, both cities" value={allCounted ? int(allCounted) : null} size="sm" />
            <Stat label={copy.peopleAtRiskEstimate} value={anyPeople ? int(peopleAtRisk) : null} size="sm" />
          </div>
          <p className="mt-3 text-[0.72rem] text-faint">
            Counts come from building_scores; demo fixtures are excluded. {copy.approximation}
          </p>
        </Panel>

        <Panel
          title="Census run"
          right={
            run?.status === "running" ? (
              <Button size="sm" tone="danger" onClick={stopRun} disabled={stopping || health.status === "unconfigured"}>
                {stopping ? "Stopping" : "Stop run"}
              </Button>
            ) : null
          }
        >
          {!run ? (
            <EmptyState title={EMPTY}>{unconfigured ? copy.supabaseMissing : copy.noRun}</EmptyState>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Badge tone={run.status === "running" ? "accent" : "muted"}>{run.status ?? EMPTY}</Badge>
                <span className="text-xs text-muted">
                  started {dateTime(run.started_at)}
                  {run.finished_at ? `, finished ${dateTime(run.finished_at)}` : ""}
                </span>
              </div>
              <div>
                <div className="mb-1.5 flex justify-between text-sm">
                  <span className="text-muted">Buildings</span>
                  <span className="num">
                    {int(run.buildings_done)} / {int(run.buildings_target)}
                  </span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-raised">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${(runFrac ?? 0) * 100}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Stat label="Panoramas" value={int(run.panos_done)} size="sm" />
                <Stat label="Spent (estimate)" value={usd(run.est_cost_usd)} size="sm" />
              </div>
              {run.notes && <p className="text-xs text-muted">{run.notes}</p>}
              {stopMsg && <p className="text-xs text-muted">{stopMsg}</p>}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid min-h-[520px] flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="relative min-h-[420px] overflow-hidden rounded-lg border border-line">
          <CityMap
            points={points}
            focus={{ key: city, center: cityInfo.center, zoom: 10 }}
            onSelect={(id) => router.push(`/building/${id}`)}
          />
          <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-md border border-line bg-panel/90 px-3 py-2 text-xs">
            <div className="label mb-1.5">{assetTitle(gap)} gap</div>
            <div className="flex items-center gap-3">
              {[
                { c: redColor(0), l: "none red" },
                { c: redColor(0.05), l: "some red" },
                { c: redColor(1), l: "all red" },
                { c: redColor(null), l: "not measured" },
              ].map((x) => (
                <span key={x.l} className="flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full" style={{ background: x.c }} />
                  {x.l}
                </span>
              ))}
            </div>
          </div>
          {points.length === 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-3 z-[500] mx-auto w-fit rounded-md border border-line bg-panel/90 px-3 py-2 text-sm text-muted">
              {unconfigured
                ? copy.supabaseMissing
                : scores.loaded
                  ? `No measured buildings in ${city} yet.`
                  : "Loading buildings"}
            </div>
          )}
        </div>

        <Panel title={`Ranked, ${city}`} className="flex min-h-0 flex-col" bodyClassName="min-h-0 flex-1 overflow-y-auto p-0">
          {ranked.length === 0 ? (
            <div className="p-4">
              <EmptyState title={EMPTY}>{unconfigured ? copy.supabaseMissing : "No ranked buildings yet."}</EmptyState>
            </div>
          ) : (
            <ol>
              {ranked.slice(0, 200).map(({ s, b }) => {
                const g = gapOf(s, gap);
                const none = g.worst === null && g.red === 1;
                return (
                  <li key={b.id}>
                    <Link
                      href={`/building/${b.id}`}
                      className="flex items-center gap-3 border-b border-line/70 px-4 py-2.5 hover:bg-raised"
                    >
                      <span className="num w-8 shrink-0 text-right text-sm text-muted">{s.rank ?? EMPTY}</span>
                      <span className="size-2.5 shrink-0 rounded-full" style={{ background: redColor(g.red) }} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{b.name ?? "Building"}</span>
                        <span className="block truncate text-xs text-muted">
                          {none ? copy.noneVisible(gap) : `worst ${formatMeasure(gap, g.worst, t)}`}
                          {isFixture(b) ? `, ${copy.fixtureTag}` : ""}
                        </span>
                      </span>
                      <span className="text-right">
                        <span className={cx("num block text-sm font-semibold", g.red && g.red > 0 ? "text-zone-red" : "text-text")}>
                          {pct(g.red)}
                        </span>
                        <span className="num block text-[0.7rem] text-muted">
                          {s.people_at_risk !== null ? `${int(s.people_at_risk)} at risk` : EMPTY}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>
      </div>
    </div>
  );
}
