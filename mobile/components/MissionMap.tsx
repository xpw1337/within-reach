import { useEffect, useMemo, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import MapView, { Circle, Marker, Polyline } from 'react-native-maps';

import { LEG_COLORS } from './theme';
import type { Fire, LatLng, Leg, Place } from '../lib/types';

type Props = {
  person: LatLng;
  me: LatLng | null;
  legs: Leg[];
  activeLeg: number;
  fire: Fire | null;
  aeds: Place[];
  extinguishers: Place[];
};

function Pin({ color, glyph }: { color: string; glyph: string }) {
  return (
    <View style={[styles.pin, { backgroundColor: color }]}>
      <Text style={styles.pinText}>{glyph}</Text>
    </View>
  );
}

/** The route on a real map: you, the person, equipment, the fire zone. Native only (see .web.tsx). */
export function MissionMap({ person, me, legs, activeLeg, fire, aeds, extinguishers }: Props) {
  const ref = useRef<MapView>(null);
  const points = useMemo(() => {
    const pts: LatLng[] = [person];
    if (me) pts.push(me);
    for (const leg of legs) pts.push(leg.to);
    return pts;
  }, [person, me, legs]);

  // Fit everything once the route is known, and again when the route changes.
  const fitKey = legs.map((l) => `${l.kind}:${l.to.lat.toFixed(5)}`).join('|') + (me ? 'me' : '');
  useEffect(() => {
    const coords = points.map((p) => ({ latitude: p.lat, longitude: p.lng }));
    if (coords.length < 2) return;
    const t = setTimeout(() => {
      ref.current?.fitToCoordinates(coords, {
        edgePadding: { top: 60, right: 50, bottom: 60, left: 50 },
        animated: true,
      });
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  const shownAeds = aeds.slice(0, 5);
  const shownExt = extinguishers.slice(0, 5);
  return (
    <MapView
      ref={ref}
      style={StyleSheet.absoluteFill}
      initialRegion={{ latitude: person.lat, longitude: person.lng, latitudeDelta: 0.004, longitudeDelta: 0.004 }}
      showsUserLocation
      showsCompass
      showsBuildings
      pitchEnabled={false}
    >
      {legs.map((leg, i) => (
        <Polyline
          key={`leg-${i}`}
          coordinates={leg.geometry.map(([lat, lng]) => ({ latitude: lat, longitude: lng }))}
          strokeColor={i < activeLeg ? '#9CA3AF' : LEG_COLORS[leg.kind]}
          strokeWidth={i === activeLeg ? 6 : 4}
          lineDashPattern={leg.source === 'direct' ? [8, 6] : undefined}
        />
      ))}
      {fire?.active ? (
        <Circle
          center={{ latitude: fire.lat, longitude: fire.lng }}
          radius={fire.radius_m}
          fillColor="rgba(234, 88, 12, 0.28)"
          strokeColor="rgba(234, 88, 12, 0.9)"
          strokeWidth={2}
        />
      ) : null}
      {shownAeds.map((p) => (
        <Marker key={p.id} coordinate={{ latitude: p.lat, longitude: p.lng }} title="AED" description={p.label}>
          <Pin color={LEG_COLORS.aed} glyph="AED" />
        </Marker>
      ))}
      {shownExt.map((p) => (
        <Marker key={p.id} coordinate={{ latitude: p.lat, longitude: p.lng }} title="Fire extinguisher" description={p.label}>
          <Pin color={LEG_COLORS.extinguisher} glyph="EXT" />
        </Marker>
      ))}
      {fire?.active ? (
        <Marker coordinate={{ latitude: fire.lat, longitude: fire.lng }} title="Fire">
          <Pin color="#EA580C" glyph="FIRE" />
        </Marker>
      ) : null}
      <Marker coordinate={{ latitude: person.lat, longitude: person.lng }} title="Person who needs help">
        <Pin color={LEG_COLORS.person} glyph="SOS" />
      </Marker>
    </MapView>
  );
}

const styles = StyleSheet.create({
  pin: {
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  pinText: { color: '#FFFFFF', fontWeight: '800', fontSize: 11 },
});
