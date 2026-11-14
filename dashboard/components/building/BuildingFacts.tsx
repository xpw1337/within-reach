import type { ReactNode } from "react";
import { Badge, Panel, Stat } from "@/components/ui";
import { assetTitle, copy, EMPTY } from "@/lib/copy";
import { int, pct } from "@/lib/format";
import { GAP_TYPES, type Asset, type Building, type BuildingScore, type GapType } from "@/lib/rows";
import { measure, type Thresholds } from "@/lib/thresholds";

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/60 py-1.5 last:border-b-0">
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="num text-right text-sm text-text">{v === null || v === undefined || v === "" ? EMPTY : v}</dd>
    </div>
  );
}

export function CostarFacts({ building }: { building: Building | null }) {
  return (
    <Panel title="CoStar facts">
      <dl>
        <Row k="Property type" v={building?.property_type} />
        <Row k="Floors" v={int(building?.floors)} />
        <Row k="Size" v={building?.size_sqft != null ? `${int(building.size_sqft)} sq ft` : null} />
        <Row k="Tenants" v={int(building?.tenants_count)} />
        <Row k="Occupancy (estimate)" v={int(building?.occupancy_est)} />
        <Row k="CoStar ID" v={building?.costar_property_id} />
        <Row k="Census status" v={building?.census_status} />
      </dl>
    </Panel>
  );
}

function worst(score: BuildingScore | null, t: GapType) {
  if (!score) return { worst: null, red: null };
  if (t === "aed") return { worst: score.aed_worst_s, red: score.aed_red_frac };
  if (t === "extinguisher") return { worst: score.ext_worst_s, red: score.ext_red_frac };
  return { worst: score.exit_worst_s, red: score.exit_red_frac };
}

export function ScoreSummary({
  score,
  thresholds,
  selected,
}: {
  score: BuildingScore | null;
  thresholds: Thresholds | null;
  selected: GapType;
}) {
  return (
    <Panel title="Measured gaps" right={score?.rank != null ? <Badge tone="accent">rank {score.rank}</Badge> : null}>
      <div className="grid grid-cols-3 gap-4">
        {GAP_TYPES.map((t) => {
          const w = worst(score, t);
          const m = measure(t, w.worst, thresholds);
          const noneVisible = score && w.worst === null && w.red === 1;
          return (
            <div key={t} className={t === selected ? "" : "opacity-75"}>
              <Stat
                label={`${assetTitle(t)} worst`}
                value={m?.value}
                unit={m ? `${m.unit} ${m.note}` : undefined}
                tone={w.red && w.red > 0 ? "red" : w.red === 0 ? "green" : undefined}
                note={
                  noneVisible ? (
                    <span className="text-zone-red">{copy.noneVisible(t)}</span>
                  ) : (
                    <>
                      <span className="num">{pct(w.red)}</span> red
                    </>
                  )
                }
              />
            </div>
          );
        })}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-3">
        <Stat label={copy.peopleAtRiskEstimate} value={score ? int(score.people_at_risk) : null} size="sm" />
        <Stat label="Worst gap" value={score?.worst_gap ? assetTitle(score.worst_gap) : null} size="sm" />
      </div>
      <p className="mt-3 text-[0.72rem] text-faint">Red share is {copy.redShareOfPositions}.</p>
    </Panel>
  );
}

export function FlagsList({
  score,
  assets,
  mapped,
}: {
  score: BuildingScore | null;
  assets: Asset[];
  mapped: boolean;
}) {
  const real = assets.filter((a) => a.source !== "proposed");
  const blockedAssets = real.filter((a) => (a.flags ?? []).includes("blocked_exit"));
  const blockedCount = score?.blocked_exits ?? (blockedAssets.length || null);
  const flags: { tone: "red" | "warn"; text: string; detail?: string }[] = [];
  if (score?.stairs_only) flags.push({ tone: "warn", text: copy.stairsOnly });
  if (blockedCount && blockedCount > 0) {
    flags.push({
      tone: "red",
      text: copy.blockedExits(blockedCount),
      detail: blockedAssets.map((a) => a.label).filter(Boolean).join(", ") || undefined,
    });
  }
  if (mapped) {
    for (const t of ["aed", "extinguisher"] as const) {
      if (!real.some((a) => a.type === t)) flags.push({ tone: "red", text: copy.noneVisible(t) });
    }
    if (!real.some((a) => a.type === "exit" || a.type === "exit_sign")) {
      flags.push({ tone: "warn", text: copy.noneVisible("exit") });
    }
  }
  return (
    <Panel title="Flags">
      {!mapped && flags.length === 0 ? (
        <p className="text-sm text-muted">{copy.notMapped}.</p>
      ) : flags.length === 0 ? (
        <p className="text-sm text-muted">No flags from the census.</p>
      ) : (
        <ul className="space-y-2">
          {flags.map((f) => (
            <li key={f.text} className="flex items-start gap-2 text-sm">
              <span className={f.tone === "red" ? "mt-1.5 size-2 rounded-full bg-zone-red" : "mt-1.5 size-2 rounded-full bg-warn"} />
              <span>
                {f.text}
                {f.detail && <span className="block text-xs text-muted">{f.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
