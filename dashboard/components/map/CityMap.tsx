"use client";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import type * as Leaflet from "leaflet";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { OSM } from "./MiniMap";

export type CityPoint = {
  id: string;
  lat: number;
  lng: number;
  /** Red fraction for the selected gap, or null when not measured. */
  red: number | null;
  label: string;
};

/** Green when nothing is red; red shades by how much is red; gray when not measured. */
export function redColor(red: number | null): string {
  if (red === null || !Number.isFinite(red)) return "#5b6676";
  if (red <= 0) return "#2ec27e";
  const f = Math.min(1, Math.max(0, red));
  const light = 76 - f * 26;
  return `hsl(358, 100%, ${light}%)`;
}

type MarkerWithRed = Leaflet.Marker & { options: Leaflet.MarkerOptions & { wrRed?: number | null } };

function dotIcon(L: typeof Leaflet, red: number | null): Leaflet.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="wr-dot" style="width:14px;height:14px;background:${redColor(red)}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

/**
 * Leaflet + OpenStreetMap tiles with marker clustering for thousands of
 * buildings. Leaflet is driven directly: the map lives for as long as the
 * effect does, and markers are diffed in place when scores stream in.
 */
export function CityMap({
  points,
  focus,
  onSelect,
}: {
  points: CityPoint[];
  /** Fit to these points, or center here when there are none. */
  focus: { key: string; center: [number, number]; zoom: number };
  onSelect: (id: string) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const lib = useRef<typeof Leaflet | null>(null);
  const map = useRef<Leaflet.Map | null>(null);
  const cluster = useRef<Leaflet.MarkerClusterGroup | null>(null);
  const markers = useRef(new Map<string, { marker: MarkerWithRed; sig: string }>());
  const [ready, setReady] = useState(0);
  const select = useEffectEvent((id: string) => onSelect(id));

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let cancelled = false;
    const registry = markers.current;
    void (async () => {
      const L = (await import("leaflet")).default;
      // The plugin attaches itself to the global L that Leaflet sets.
      await import("leaflet.markercluster");
      if (cancelled) return;
      const m = L.map(node, { zoomControl: true, preferCanvas: true, worldCopyJump: true });
      L.tileLayer(OSM.url, { attribution: OSM.attribution, maxZoom: 19 }).addTo(m);
      const group = L.markerClusterGroup({
        chunkedLoading: true,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        maxClusterRadius: 48,
        iconCreateFunction: (c) => {
          const children = c.getAllChildMarkers() as MarkerWithRed[];
          const measured = children.filter((k) => typeof k.options.wrRed === "number");
          const withRed = measured.filter((k) => (k.options.wrRed as number) > 0).length;
          const share = measured.length ? withRed / measured.length : null;
          const n = c.getChildCount();
          const size = n < 10 ? 34 : n < 100 ? 40 : n < 1000 ? 48 : 56;
          return L.divIcon({
            className: "",
            html: `<div class="wr-cluster" style="width:${size}px;height:${size}px;background:${redColor(share)}">${n}</div>`,
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
          });
        },
      });
      m.addLayer(group);
      lib.current = L;
      map.current = m;
      cluster.current = group;
      setReady((r) => r + 1);
    })();
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
      cluster.current = null;
      registry.clear();
    };
  }, []);

  // Diff markers in place.
  useEffect(() => {
    const L = lib.current;
    const group = cluster.current;
    if (!L || !group || !ready) return;
    const registry = markers.current;
    const seen = new Set<string>();
    const toAdd: Leaflet.Marker[] = [];
    const changed: Leaflet.Marker[] = [];
    for (const p of points) {
      seen.add(p.id);
      const sig = `${p.red}|${p.lat}|${p.lng}|${p.label}`;
      const existing = registry.get(p.id);
      if (existing) {
        if (existing.sig !== sig) {
          existing.marker.options.wrRed = p.red;
          existing.marker.setIcon(dotIcon(L, p.red));
          existing.marker.setLatLng([p.lat, p.lng]);
          existing.marker.setTooltipContent(p.label);
          existing.sig = sig;
          changed.push(existing.marker);
        }
        continue;
      }
      const marker = L.marker([p.lat, p.lng], { icon: dotIcon(L, p.red), title: p.label }) as MarkerWithRed;
      marker.options.wrRed = p.red;
      marker.bindTooltip(p.label);
      marker.on("click", () => select(p.id));
      registry.set(p.id, { marker, sig });
      toAdd.push(marker);
    }
    const toRemove: Leaflet.Marker[] = [];
    for (const [id, v] of registry) {
      if (!seen.has(id)) {
        toRemove.push(v.marker);
        registry.delete(id);
      }
    }
    if (toRemove.length) group.removeLayers(toRemove);
    if (toAdd.length) group.addLayers(toAdd);
    if (changed.length) group.refreshClusters(changed);
  }, [points, ready]);

  // Re-frame when the city changes (not on every score update).
  const frame = useEffectEvent(() => {
    const L = lib.current;
    const m = map.current;
    if (!L || !m) return;
    if (points.length > 0) {
      m.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number])), {
        padding: [40, 40],
        maxZoom: 15,
      });
    } else {
      m.setView(focus.center, focus.zoom);
    }
  });
  const hasPoints = points.length > 0;
  useEffect(() => {
    if (ready) frame();
  }, [focus.key, ready, hasPoints]);

  return <div ref={el} className="map-dim h-full min-h-[420px] w-full" />;
}
