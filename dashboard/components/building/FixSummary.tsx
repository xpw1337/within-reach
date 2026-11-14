import { Panel } from "@/components/ui";
import { assetName, assetTitle, copy } from "@/lib/copy";
import { pct } from "@/lib/format";
import type { Fix, GapType, TwinNode } from "@/lib/rows";
import { measure, type Thresholds } from "@/lib/thresholds";

/** "Worst case X -> Y; red area A% -> B%", straight from the fixes row (spec section 9.6). */
export function FixSummary({
  fix,
  type,
  thresholds,
  nodes,
  unconnected,
  children,
}: {
  fix: Fix | null;
  type: GapType;
  thresholds: Thresholds | null;
  nodes: TwinNode[];
  unconnected?: number;
  children?: React.ReactNode;
}) {
  const before = measure(type, fix?.before_worst_s, thresholds);
  const after = measure(type, fix?.after_worst_s, thresholds);
  const unitNote = (after ?? before)?.note;
  const sweep = fix?.sweep_id ? nodes.find((n) => n.sweep_id === fix.sweep_id) : undefined;
  return (
    <Panel title={`Agent fix: one new ${assetName(type)}`}>
      {type === "exit" ? (
        <p className="text-sm text-muted">The Fixer proposes AEDs and extinguishers. Exits are reported, not placed.</p>
      ) : !fix ? (
        <p className="text-sm text-muted">No {assetName(type)} placement from the Fixer yet.</p>
      ) : (
        <div className="space-y-3">
          <div>
            <div className="label">Worst case</div>
            <div className="num mt-1 flex items-baseline gap-2 text-3xl font-bold">
              <span className="text-zone-red">{before ? `${before.value} ${before.unit}` : "--"}</span>
              <span className="text-xl text-muted">→</span>
              <span className="text-zone-green">{after ? `${after.value} ${after.unit}` : "--"}</span>
              {unitNote && <span className="text-sm font-medium text-muted">{unitNote}</span>}
            </div>
          </div>
          <div>
            <div className="label">Red area</div>
            <div className="num mt-1 flex items-baseline gap-2 text-2xl font-bold">
              <span className="text-zone-red">{pct(fix.before_red_frac)}</span>
              <span className="text-lg text-muted">→</span>
              <span className="text-zone-green">{pct(fix.after_red_frac)}</span>
              <span className="text-sm font-medium text-muted">{copy.redShareOfPositions}</span>
            </div>
            {unconnected ? <div className="mt-1 text-xs text-muted">{copy.unconnected(unconnected)}</div> : null}
          </div>
          <div className="text-sm">
            <span className="text-muted">New {assetTitle(type)} at </span>
            <span className="font-semibold">{sweep?.label || sweep?.room_type || fix.sweep_id || "--"}</span>
            {sweep && <span className="text-muted">, floor {sweep.floor ?? 0}</span>}
          </div>
          {fix.rationale && <p className="text-sm leading-relaxed text-muted">{fix.rationale}</p>}
        </div>
      )}
      {children && <div className="mt-4 border-t border-line pt-3">{children}</div>}
    </Panel>
  );
}
