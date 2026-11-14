"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";
import { Badge, Button, cx, EmptyState, Panel, Stat } from "@/components/ui";
import { api, type ApiFailure, type HandcheckItem, type HandcheckSummary, type HumanLabel } from "@/lib/api";
import { assetTitle, copy, EMPTY } from "@/lib/copy";
import { int, pct } from "@/lib/format";

const LABELS: { value: HumanLabel; text: string; keys: string; tone: "ok" | "danger" | "default" }[] = [
  { value: "correct", text: "Correct", keys: "C or 1", tone: "ok" },
  { value: "incorrect", text: "Incorrect", keys: "X or 2", tone: "danger" },
  { value: "unsure", text: "Unsure", keys: "U or 3", tone: "default" },
];
const KEYMAP: Record<string, HumanLabel> = { c: "correct", "1": "correct", x: "incorrect", "2": "incorrect", u: "unsure", "3": "unsure" };

type Load = { state: "loading" } | { state: "ok" } | { state: "error"; error: ApiFailure };

export function HandcheckView() {
  const [items, setItems] = useState<HandcheckItem[]>([]);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [idx, setIdx] = useState(0);
  const [labels, setLabels] = useState<Record<string, HumanLabel>>({});
  const [summary, setSummary] = useState<HandcheckSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refreshSummary = useCallback(async () => {
    const res = await api.getHandcheckSummary();
    if (res.ok) setSummary(res.data);
  }, []);

  const fetchSample = useCallback(async () => {
    setLoad({ state: "loading" });
    const res = await api.getHandcheck(30);
    if (!res.ok) {
      setLoad({ state: "error", error: res });
      return;
    }
    setItems(Array.isArray(res.data) ? res.data : []);
    setIdx(0);
    setLabels({});
    setLoad({ state: "ok" });
    void refreshSummary();
  }, [refreshSummary]);

  useEffect(() => {
    const id = window.setTimeout(() => void fetchSample(), 0);
    return () => window.clearTimeout(id);
  }, [fetchSample]);

  const item = items[idx] ?? null;

  async function label(value: HumanLabel) {
    if (!item || saving) return;
    setSaving(true);
    setErr(null);
    const res = await api.labelDetection(item.detection_id, value);
    setSaving(false);
    if (!res.ok) {
      setErr(`Label not saved: ${res.error}`);
      return;
    }
    const next = { ...labels, [item.detection_id]: value };
    setLabels(next);
    void refreshSummary();
    // Advance to the next item without a label from this session.
    for (let k = 1; k <= items.length; k++) {
      const j = (idx + k) % items.length;
      if (!next[items[j].detection_id]) {
        setIdx(j);
        return;
      }
    }
  }

  const onKey = useEffectEvent((e: KeyboardEvent) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
    const k = e.key.toLowerCase();
    if (KEYMAP[k]) {
      e.preventDefault();
      void label(KEYMAP[k]);
    } else if (k === "arrowright" || k === "j") {
      setIdx((i) => Math.min(items.length - 1, i + 1));
    } else if (k === "arrowleft" || k === "k") {
      setIdx((i) => Math.max(0, i - 1));
    }
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => onKey(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const doneHere = Object.keys(labels).length;
  const precision =
    summary && summary.correct + summary.incorrect > 0 ? summary.correct / (summary.correct + summary.incorrect) : null;

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Hand-check</h1>
          <p className="mt-1 text-sm text-muted">
            A random sample of the Scanner&apos;s detections, labeled by a person. The count below is what we report.
          </p>
        </div>
        <Button onClick={() => void fetchSample()} disabled={load.state === "loading"}>
          New sample
        </Button>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title={item ? `Detection ${idx + 1} of ${items.length}` : "Detection"}>
          {load.state === "loading" ? (
            <EmptyState title="Loading the sample" />
          ) : load.state === "error" ? (
            <EmptyState title={EMPTY}>
              {load.error.reason === "not_configured"
                ? copy.agentMissing
                : `${copy.agentUnreachable} ${load.error.error}`}
            </EmptyState>
          ) : !item ? (
            <EmptyState title="No detections to check">The census has not queued detections for hand-check yet.</EmptyState>
          ) : (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="flex min-h-[420px] items-center justify-center overflow-hidden rounded-md border border-line bg-black">
                {item.crop_url ? (
                  // Equipment crops only (spec section 9.3); sizes vary, so a plain img.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={item.crop_url}
                    alt={`Crop of a possible ${assetTitle(item.asset_type)}`}
                    className="max-h-[560px] w-auto max-w-full object-contain"
                  />
                ) : (
                  <span className="text-sm text-muted">No crop stored for this detection.</span>
                )}
              </div>
              <div className="space-y-4">
                <div>
                  <div className="label">The Scanner says</div>
                  <div className="mt-1 text-3xl font-bold">{assetTitle(item.asset_type)}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {item.status && <Badge tone="muted">{item.status}</Badge>}
                    {labels[item.detection_id] && <Badge tone="accent">labeled {labels[item.detection_id]}</Badge>}
                  </div>
                </div>
                <Stat label="Model confidence" value={item.confidence !== null ? item.confidence.toFixed(2) : null} size="sm" />
                <div className="space-y-2">
                  {LABELS.map((l) => (
                    <Button
                      key={l.value}
                      tone={l.tone}
                      size="lg"
                      className="w-full justify-between"
                      disabled={saving}
                      onClick={() => void label(l.value)}
                    >
                      <span>{l.text}</span>
                      <kbd className="rounded bg-black/20 px-1.5 py-0.5 text-xs font-semibold">{l.keys}</kbd>
                    </Button>
                  ))}
                </div>
                <p className="text-xs text-muted">Arrow keys or J and K move between detections.</p>
                {err && <p className="text-sm text-danger">{err}</p>}
              </div>
            </div>
          )}
          {items.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5" aria-label="Sample progress">
              {items.map((it, i) => {
                const l = labels[it.detection_id];
                return (
                  <button
                    key={it.detection_id}
                    type="button"
                    onClick={() => setIdx(i)}
                    aria-label={`Detection ${i + 1}${l ? `, ${l}` : ""}`}
                    className={cx(
                      "h-3 w-6 rounded-sm border",
                      i === idx ? "border-text" : "border-transparent",
                      l === "correct" ? "bg-ok" : l === "incorrect" ? "bg-danger" : l === "unsure" ? "bg-zone-yellow" : "bg-raised",
                    )}
                  />
                );
              })}
            </div>
          )}
        </Panel>

        <Panel title="Precision">
          {!summary ? (
            <Stat label="Correct" value={null} size="xl" note="From GET /census/handcheck/summary." />
          ) : (
            <div className="space-y-4">
              <div>
                <div className="label">Correct</div>
                <div className="num mt-1 text-6xl leading-none font-bold">
                  {int(summary.correct)}
                  <span className="text-3xl text-muted"> / {int(summary.labeled)}</span>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 border-t border-line pt-3">
                <Stat label="Incorrect" value={int(summary.incorrect)} size="sm" />
                <Stat label="Unsure" value={int(summary.unsure)} size="sm" />
                <Stat label="Precision" value={pct(precision)} size="sm" note="excluding unsure" />
              </div>
            </div>
          )}
          <p className="mt-4 text-xs text-muted">
            Labeled in this session: <span className="num text-text">{doneHere}</span>
          </p>
        </Panel>
      </div>
    </div>
  );
}
