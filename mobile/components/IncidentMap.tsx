import { StyleSheet } from 'react-native';
import MapView, { Marker } from 'react-native-maps';

type Point = { lat: number; lng: number };

/** Map with the incident and, if known, my position. Native only (see IncidentMap.web.tsx). */
export function IncidentMap({ target, title, me }: { target: Point; title: string; me: Point | null }) {
  const points = me ? [target, me] : [target];
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const region = {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLng + maxLng) / 2,
    latitudeDelta: Math.max(0.004, (maxLat - minLat) * 1.6),
    longitudeDelta: Math.max(0.004, (maxLng - minLng) * 1.6),
  };
  return (
    <MapView style={styles.map} initialRegion={region} showsUserLocation>
      <Marker coordinate={{ latitude: target.lat, longitude: target.lng }} title={title} pinColor="red" />
    </MapView>
  );
}

const styles = StyleSheet.create({
  map: { height: 220, borderRadius: 12 },
});
