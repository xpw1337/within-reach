"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

export type MapPoint = { lat: number; lng: number; color: string; label: string; size?: number };

const OSM = {
  url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};
export { OSM };

/**
 * A small Leaflet map with a few colored points. Leaflet is driven directly
 * (not react-leaflet): the map is created in an effect and removed in its
 * cleanup, which also matches how Next hides routes with Activity.
 */
export function MiniMap({ points, height = 260 }: { points: MapPoint[]; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const key = JSON.stringify(points);

  useEffect(() => {
    const node = el.current;
    if (!node || points.length === 0) return;
    let map: import("leaflet").Map | null = null;
    let cancelled = false;
    void import("leaflet").then((mod) => {
      const L = mod.default;
      if (cancelled || !node) return;
      map = L.map(node, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
      L.tileLayer(OSM.url, { attribution: OSM.attribution, maxZoom: 19 }).addTo(map);
      const latlngs: [number, number][] = [];
      for (const p of points) {
        const s = p.size ?? 14;
        L.marker([p.lat, p.lng], {
          icon: L.divIcon({
            className: "",
            html: `<div class="wr-dot" style="width:${s}px;height:${s}px;background:${p.color}"></div>`,
            iconSize: [s, s],
            iconAnchor: [s / 2, s / 2],
          }),
          title: p.label,
        })
          .bindTooltip(p.label)
          .addTo(map);
        latlngs.push([p.lat, p.lng]);
      }
      if (latlngs.length === 1) map.setView(latlngs[0], 19);
      else map.fitBounds(L.latLngBounds(latlngs), { padding: [28, 28], maxZoom: 19 });
    });
    return () => {
      cancelled = true;
      map?.remove();
    };
    // points are compared by value through `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (points.length === 0) return null;
  return <div ref={el} className="map-dim w-full overflow-hidden rounded-md border border-line" style={{ height }} />;
}
