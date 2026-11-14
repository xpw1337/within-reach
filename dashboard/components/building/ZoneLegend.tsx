import { cx } from "@/components/ui";
import { assetName, copy } from "@/lib/copy";
import type { SweepZone } from "@/lib/heatmap";
import type { GapType } from "@/lib/rows";
import { formatLimit, formatYellowStart, type ThresholdState } from "@/lib/thresholds";

function Swatch({ zone }: { zone: SweepZone }) {
  const cls = {
    green: "bg-zone-green",
    yellow: "bg-zone-yellow",
    red: "bg-zone-red",
    unknown: "bg-zone-unknown",
    unmapped: "border border-dashed border-faint",
  }[zone];
  return <span className={cx("inline-block size-3 shrink-0 rounded-full", cls)} aria-hidden />;
}

export function ZoneLegend({
  type,
  thresholds,
  counts,
  hasAsset,
}: {
  type: GapType;
  thresholds: ThresholdState;
  counts?: Record<SweepZone, number> | null;
  hasAsset: boolean;
}) {
  const t = thresholds.thresholds;
  const n = (z: SweepZone) => (counts ? <span className="num ml-auto pl-3 text-text">{counts[z]}</span> : null);
  return (
    <div className="space-y-2 text-[0.8rem]">
      {thresholds.status === "unavailable" && (
        <div className="rounded border border-warn/40 bg-warn/10 px-2.5 py-1.5 text-xs text-warn">
          {copy.thresholdsUnavailable}
        </div>
      )}
      <ul className="space-y-1.5">
        <li className="flex items-center gap-2">
          <Swatch zone="green" />
          <span>Within reach</span>
          <span className="text-muted">up to {formatYellowStart(type, t)}</span>
          {n("green")}
        </li>
        <li className="flex items-center gap-2">
          <Swatch zone="yellow" />
          <span>Getting far</span>
          <span className="text-muted">up to {formatLimit(type, t)}</span>
          {n("yellow")}
        </li>
        <li className="flex items-center gap-2">
          <Swatch zone="red" />
          <span>Out of reach</span>
          <span className="text-muted">beyond {formatLimit(type, t)}</span>
          {n("red")}
        </li>
        <li className="flex items-center gap-2">
          <Swatch zone="unknown" />
          <span className="text-muted">
            {t ? copy.unknownZone(type, hasAsset) : `Unknown: thresholds unavailable`}
          </span>
          {n("unknown")}
        </li>
        <li className="flex items-center gap-2">
          <Swatch zone="unmapped" />
          <span className="text-muted">{copy.notMapped}</span>
          {n("unmapped")}
        </li>
      </ul>
      <p className="text-[0.72rem] leading-snug text-faint">
        {copy.approximation} {assetName(type)} times are walking times on the scan graph.
        {type === "exit" ? ` ${copy.exitApproximation}` : ""}
      </p>
    </div>
  );
}
