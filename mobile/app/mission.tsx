import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Finder } from '../components/Finder';
import { MissionMap } from '../components/MissionMap';
import { colors, font, space, type } from '../components/theme';
import { Button, Card, Chip, IconButton, Row } from '../components/ui';
import { bearingDeg, distanceM } from '../lib/geo';
import { arrived, send, useSos } from '../lib/sos';
import { say, stopSpeaking } from '../lib/speech';
import type { LatLng, Leg } from '../lib/types';

const TARGET: Record<Leg['kind'], string> = {
  extinguisher: 'Fire extinguisher',
  aed: 'AED',
  person: 'Person who fell',
};
const DONE: Record<Leg['kind'], string> = {
  extinguisher: 'I have the extinguisher',
  aed: 'I have the AED',
  person: "I'm with them",
};
const NEAR_M = 8;

/** Where to aim: the next route point a few meters ahead, or the target itself for short hops. */
function aimPoint(leg: Leg, me: LatLng): LatLng {
  const pts = leg.geometry.map(([lat, lng]) => ({ lat, lng }));
  if (leg.source === 'direct' || pts.length < 2) return leg.to;
  let nearest = 0;
  let best = Infinity;
  pts.forEach((p, i) => {
    const d = distanceM(me, p);
    if (d < best) {
      best = d;
      nearest = i;
    }
  });
  for (let i = nearest; i < pts.length; i++) if (distanceM(me, pts[i]) > 12) return pts[i];
  return leg.to;
}

function relative(bearing: number, heading: number): number {
  let r = bearing - heading;
  while (r > 180) r -= 360;
  while (r <= -180) r += 360;
  return r;
}

function sideWords(rel: number | null): [string, string] {
  if (rel === null) return ['', 'away'];
  if (Math.abs(rel) < 20) return ['ahead', ''];
  if (Math.abs(rel) > 150) return ['behind', 'you'];
  return ['to your', rel > 0 ? 'right' : 'left'];
}

export default function MissionScreen() {
  const sos = useSos();
  const mission = sos.phone?.mission ?? null;
  const [picked, setPicked] = useState<string[]>([]);
  const [showMap, setShowMap] = useState(false);
  const [voice, setVoice] = useState(true);
  const spokenFor = useRef('');
  const wasAhead = useRef(false);

  const collected = useMemo(() => [...new Set([...(mission?.collected ?? []), ...picked])], [mission?.collected, picked]);
  const legs = useMemo(
    () => (mission?.plan?.legs ?? []).filter((l) => l.kind === 'person' || !collected.includes(l.kind)),
    [mission?.plan?.legs, collected],
  );
  const leg = legs[0] ?? null;
  const me = sos.location;
  const onScene = mission?.status === 'on_scene';

  const target = leg?.to ?? mission?.location ?? null;
  const dist = me && target ? distanceM(me, target) : leg?.distance_m ?? null;
  const aim = leg && me ? aimPoint(leg, me) : null;
  const bearing = aim && me ? bearingDeg(me, aim) : null;
  const rel = bearing !== null && sos.heading !== null ? relative(bearing, sos.heading) : null;
  const near = dist !== null && dist <= NEAR_M;
  const ahead = near || (rel !== null && Math.abs(rel) < 20);

  // A tap when you turn to face it, like Find My.
  useEffect(() => {
    if (ahead && !wasAhead.current) void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    wasAhead.current = ahead;
  }, [ahead]);

  // Say each new goal once.
  useEffect(() => {
    if (!leg || onScene || !voice) return;
    const key = `${mission?.id}:${leg.kind}`;
    if (spokenFor.current === key) return;
    spokenFor.current = key;
    void say(`${leg.kind === 'person' ? 'Go to the person' : `Get the ${TARGET[leg.kind].toLowerCase()}`}. ${Math.round(dist ?? leg.distance_m)} meters.`);
  }, [leg, onScene, voice, mission?.id, dist]);

  if (!mission) {
    return (
      <SafeAreaView style={[styles.flex, styles.center]}>
        <Text style={type.title}>No active emergency</Text>
        <View style={{ width: 240 }}>
          <Button title="Home" onPress={() => router.replace('/')} />
        </View>
      </SafeAreaView>
    );
  }
  if (mission.status === 'resolved') {
    return (
      <SafeAreaView style={[styles.flex, styles.center, { padding: space.xl }]}>
        <View style={styles.doneBadge}>
          <Ionicons name="checkmark" size={64} color={colors.white} />
        </View>
        <Text style={[type.hero, { textAlign: 'center' }]}>Thank you</Text>
        <Text style={[type.body, { color: colors.muted, textAlign: 'center' }]}>The emergency is closed. You showed up.</Text>
        <View style={{ alignSelf: 'stretch' }}>
          <Button title="Done" onPress={() => router.replace('/')} />
        </View>
      </SafeAreaView>
    );
  }
  if (onScene) return <OnScene kind={mission.kind} fire={Boolean(mission.fire?.active)} hasAed={collected.includes('aed')} />;

  const fire = mission.fire?.active ? mission.fire : null;
  const bg = ahead ? colors.green : colors.white;
  const fg = ahead ? colors.white : colors.ink;
  const fg2 = ahead ? 'rgba(255,255,255,0.75)' : colors.faint;
  const [side1, side2] = near ? ['nearby', ''] : sideWords(rel);
  const dnum = dist === null ? '--' : dist >= 1000 ? (dist / 1000).toFixed(1) : String(Math.max(1, Math.round(dist)));
  const dunit = dist !== null && dist >= 1000 ? 'km' : 'm';

  function done() {
    if (!leg) return;
    stopSpeaking();
    if (leg.kind === 'person') arrived();
    else {
      setPicked((p) => [...p, leg.kind]);
      send({ type: 'collected', what: leg.kind });
    }
  }

  if (showMap && mission.location) {
    return (
      <View style={styles.flex}>
        <MissionMap
          person={mission.location}
          me={me}
          legs={legs}
          activeLeg={0}
          fire={fire}
          aeds={mission.resources?.aeds ?? []}
          extinguishers={mission.resources?.extinguishers ?? []}
        />
        <SafeAreaView edges={['top', 'bottom']} style={styles.mapOverlay} pointerEvents="box-none">
          <IconButton icon="close" label="Back to the arrow" bg={colors.white} onPress={() => setShowMap(false)} />
          <View style={{ flex: 1 }} pointerEvents="none" />
          {leg ? <Button title={DONE[leg.kind]} kind={leg.kind === 'person' ? 'green' : 'primary'} onPress={done} /> : null}
        </SafeAreaView>
      </View>
    );
  }

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: bg }]} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.finding, { color: fg2 }]}>FINDING</Text>
          <Text style={[styles.target, { color: fg }]} numberOfLines={1}>{leg ? TARGET[leg.kind] : 'Person who fell'}</Text>
          {leg?.to.label && leg.kind !== 'person' ? (
            <Text style={[styles.place, { color: fg2 }]} numberOfLines={1}>{leg.to.label}</Text>
          ) : null}
        </View>
        {legs.length > 1 ? <Chip text={`then ${legs.slice(1).map((l) => (l.kind === 'person' ? 'person' : TARGET[l.kind])).join(' → ')}`} /> : null}
      </View>

      {fire ? (
        <View style={styles.chips}>
          <Chip text={leg?.avoids_fire ? 'Route avoids the fire' : 'Fire nearby: keep your distance'} tone="orange" icon="flame" />
        </View>
      ) : null}

      <View style={styles.center}>
        {mission.plan ? (
          <Finder rel={rel} near={near} color={fg} />
        ) : (
          <Text style={[type.heading, { color: colors.muted }]}>{me ? 'Finding the fastest way...' : 'Waiting for your location...'}</Text>
        )}
      </View>

      <View style={styles.readout}>
        <Text style={[styles.big, { color: fg }]}>
          {dnum} <Text style={{ color: fg2 }}>{dunit}</Text>
        </Text>
        <Text style={[styles.big, { color: fg }]}>
          {side1} <Text style={{ color: fg2 }}>{side2}</Text>
        </Text>
        {rel === null && mission.plan ? (
          <Text style={[styles.hint, { color: fg2 }]}>Hold the phone flat to use the compass</Text>
        ) : null}
      </View>

      <View style={styles.actions}>
        <IconButton icon="map" label="Show map" tint={fg} bg={ahead ? 'rgba(255,255,255,0.25)' : colors.surface} onPress={() => setShowMap(true)} />
        <View style={{ flex: 1 }}>
          {leg ? <Button title={DONE[leg.kind]} kind={ahead ? 'white' : leg.kind === 'person' ? 'green' : 'primary'} onPress={done} /> : null}
        </View>
        <IconButton
          icon={voice ? 'volume-high' : 'volume-mute'}
          label={voice ? 'Mute voice' : 'Voice on'}
          tint={fg}
          bg={ahead ? 'rgba(255,255,255,0.25)' : colors.surface}
          onPress={() => {
            if (voice) stopSpeaking();
            setVoice((v) => !v);
          }}
        />
      </View>
    </SafeAreaView>
  );
}

function OnScene({ kind, fire, hasAed }: { kind: 'fall' | 'fire'; fire: boolean; hasAed: boolean }) {
  return (
    <SafeAreaView style={styles.flex} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg }}>
        <Chip text="You're with them" tone="green" icon="checkmark-circle" />
        {kind === 'fall' ? (
          <>
            <Text style={type.hero}>Check if they respond</Text>
            <Text style={type.body}>
              Tap their shoulder and shout. If they don&apos;t respond and aren&apos;t breathing normally, start CPR.
            </Text>
            <Button title="Start CPR" icon="pulse" onPress={() => router.push({ pathname: '/cpr', params: { live: '1' } })} />
            <Button title="Help me use the AED" kind={hasAed ? 'green' : 'secondary'} icon="flash" onPress={() => router.push('/aed-help')} />
          </>
        ) : (
          <Text style={type.hero}>Stay safe</Text>
        )}
        {fire ? (
          <Card tone="orange">
            <Row icon="flame" tint={colors.orangeDark} title="Using the extinguisher" detail="Only if the fire is small and your way out is clear." />
            <Text style={type.body}>Pull the pin. Aim at the base. Squeeze the handle. Sweep side to side.</Text>
          </Card>
        ) : null}
        <Card>
          <Row icon="call" tint={colors.red} title="911 has been called" detail="By the Within Reach agent (simulated in this demo)" />
        </Card>
        <Button title="Home" kind="ghost" onPress={() => router.replace('/')} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.white },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, paddingHorizontal: space.xl, paddingTop: space.md },
  finding: { fontFamily: font.heavy, fontSize: 13, letterSpacing: 1.4 },
  target: { fontFamily: font.black, fontSize: 32, lineHeight: 38 },
  place: { fontFamily: font.bold, fontSize: 15 },
  chips: { paddingHorizontal: space.xl, paddingTop: space.sm },
  readout: { paddingHorizontal: space.xl, paddingBottom: space.md },
  big: { fontFamily: font.heavy, fontSize: 46, lineHeight: 52, fontVariant: ['tabular-nums'] },
  hint: { fontFamily: font.bold, fontSize: 14, marginTop: space.xs },
  actions: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.xl, paddingBottom: space.md },
  mapOverlay: { ...StyleSheet.absoluteFill, padding: space.lg, gap: space.md },
  doneBadge: { width: 120, height: 120, borderRadius: 60, backgroundColor: colors.green, alignItems: 'center', justifyContent: 'center', borderBottomWidth: 6, borderBottomColor: colors.greenDark },
});
