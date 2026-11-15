import { StyleSheet, Text, View } from 'react-native';

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

/** react-native-maps has no web support; the web build (bundle checks only) shows a summary. */
export function MissionMap({ person, legs }: Props) {
  return (
    <View style={styles.box}>
      <Text style={styles.text}>The map shows on the phone.</Text>
      <Text style={styles.text}>
        Person at {person.lat.toFixed(5)}, {person.lng.toFixed(5)}. {legs.length} leg(s).
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center', backgroundColor: '#E5E7EB' },
  text: { color: '#374151' },
});
