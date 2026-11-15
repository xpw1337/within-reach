"use client";

import "leaflet/dist/leaflet.css";
import type * as Leaflet from "leaflet";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { OSM } from "@/components/map/MiniMap";
import type { Camera, Incident, Place, Responder } from "@/lib/sos";

export type ClickMode = "none" | "fire" | "aed" | "extinguisher";

const LEG_COLORS = { extinguisher: "#ff8a00", aed: "#34c759", person: "#ed1b2e" } as const;

function tag(L: typeof Leaflet, text: string, bg: string, pulse = false): Leaflet.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="wr-tag${pulse ? " wr-pulse" : ""}" style="background:${bg}">${text}</div>`,
    iconSize: undefined,
    iconAnchor: [18, 12],
  });
}

/**
 * Live map: the camera (person), responders, AEDs and extinguishers, the fire zone and the
 * accepted responder's route. Clicking places a fire or an equipment pin when a mode is chosen.
 */
export function LiveMap({
  cameras,
  responders,
  incident,
  pinned,
  mode,
  onPick,
}: {
  cameras: Camera[];
  responders: Responder[];
  incident: Incident | null;
  pinned: Place[];
  mode: ClickMode;
  onPick: (lat: number, lng: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<Leaflet.Map | null>(null);
  const layer = useRef<Leaflet.LayerGroup | null>(null);
  const lib = useRef<typeof Leaflet | null>(null);
  const fitted = useRef<string>("");
  const [ready, setReady] = useState(false);
  const pick = useEffectEvent((lat: number, lng: number) => onPick(lat, lng));

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let cancelled = false;
    void import("leaflet").then((mod) => {
      const L = mod.default;
      if (cancelled) return;
      lib.current = L;
      const m = L.map(node, { zoomControl: true, attributionControl: true }).setView([20, 0], 2);
      L.tileLayer(OSM.url, { attribution: OSM.attribution, maxZoom: 20, maxNativeZoom: 19 }).addTo(m);
      layer.current = L.layerGroup().addTo(m);
      m.on("click", (e: Leaflet.LeafletMouseEvent) => pick(e.latlng.lat, e.latlng.lng));
      map.current = m;
      setReady(true);
    });
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const L = lib.current;
    const m = map.current;
    const g = layer.current;
    if (!L || !m || !g) return;
    g.clearLayers();
    const pts: [number, number][] = [];
    const inc = incident && incident.status !== "resolved" ? incident : null;

    for (const c of cameras) {
      L.marker([c.lat, c.lng], { icon: tag(L, inc ? "SOS" : "CAM", inc ? "#ed1b2e" : "#1a1a1a", Boolean(inc)) })
        .bindTooltip(`Camera: ${c.label}`)
        .addTo(g);
      if (c.accuracy_m) L.circle([c.lat, c.lng], { radius: c.accuracy_m, color: "#ed1b2e", weight: 1, fillOpacity: 0.04 }).addTo(g);
      pts.push([c.lat, c.lng]);
    }
    if (inc?.fire?.active) {
      const f = inc.fire;
      L.circle([f.lat, f.lng], { radius: f.radius_m, color: "#ff8a00", weight: 2, fillColor: "#ff8a00", fillOpacity: 0.28 }).addTo(g);
      L.marker([f.lat, f.lng], { icon: tag(L, "FIRE", "#ff8a00", true) }).addTo(g);
      pts.push([f.lat, f.lng]);
    }
    const places = inc ? [...inc.resources.aeds.slice(0, 8), ...inc.resources.extinguishers.slice(0, 8)] : pinned;
    const seen = new Set<string>();
    for (const p of [...places, ...pinned]) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      const color = p.kind === "aed" ? LEG_COLORS.aed : LEG_COLORS.extinguisher;
      L.marker([p.lat, p.lng], { icon: tag(L, p.kind === "aed" ? "AED" : "EXT", color) })
        .bindTooltip(`${p.label} (${p.source === "pinned" ? "pinned by you" : "OpenStreetMap"})`)
        .addTo(g);
    }
    for (const leg of inc?.plan?.legs ?? []) {
      L.polyline(leg.geometry, {
        color: LEG_COLORS[leg.kind],
        weight: 5,
        opacity: 0.9,
        dashArray: leg.source === "direct" ? "8 8" : undefined,
      }).addTo(g);
    }
    for (const r of responders) {
      if (r.lat === null || r.lng === null) continue;
      const assigned = inc?.responder_id === r.id;
      const color = assigned ? "#34c759" : r.available ? "#1a1a1a" : "#afafaf";
      L.marker([r.lat, r.lng], { icon: tag(L, r.name.slice(0, 12), color) })
        .bindTooltip(`${r.name}${assigned ? " (responding)" : r.available ? " (available)" : " (unavailable)"}`)
        .addTo(g);
      if (assigned || inc) pts.push([r.lat, r.lng]);
    }

    const key = `${inc?.id ?? "none"}:${cameras.length}:${inc?.responder_id ?? ""}:${inc?.plan ? 1 : 0}`;
    if (pts.length && fitted.current !== key) {
      fitted.current = key;
      // The container may have just been laid out (dynamic import): measure before fitting.
      setTimeout(() => {
        m.invalidateSize();
        const size = m.getSize();
        if (!size.x || !size.y) {
          fitted.current = ""; // not laid out yet: try again on the next update
          return;
        }
        const bounds = L.latLngBounds(pts);
        // Points a few meters apart (camera and a responder in the same room) make fitBounds
        // zoom all the way out; center on them at street level instead.
        const spread = bounds.getSouthWest().distanceTo(bounds.getNorthEast());
        if (spread < 60) m.setView(bounds.getCenter(), 19);
        else m.fitBounds(bounds.pad(0.3), { maxZoom: 19 });
      }, 60);
    }
  }, [ready, cameras, responders, incident, pinned]);

  useEffect(() => {
    if (el.current) el.current.style.cursor = mode === "none" ? "" : "crosshair";
  }, [mode]);

  return <div ref={el} className="h-full min-h-[320px] w-full rounded-md" />;
}
