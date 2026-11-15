import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, space } from '../components/theme';
import { Button } from '../components/ui';
import { stopAlarm } from '../lib/alarm';
import { bearingDeg, compassWord, distanceM, formatDistance } from '../lib/geo';
import { accept, decline, useSos } from '../lib/sos';

function goHome() {
  if (router.canGoBack()) router.back();
  else router.replace('/');
}

function Beacon({ fire }: { fire: boolean }) {
  const [v] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1400, easing: Easing.out(Easing.quad), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [v]);
  const ring = (delay: number) => ({
    opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.55 - delay, 0] }),
    transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1 + delay, 2.1 + delay] }) }],
  });
  return (
    <View style={styles.beacon}>
      <Animated.View style={[styles.ring, ring(0)]} />
      <Animated.View style={[styles.ring, ring(0.25)]} />
      <View style={styles.beaconCore}>
        <Ionicons name={fire ? 'flame' : 'body'} size={54} color={colors.red} />
      </View>
    </View>
  );
}

/** Full-screen incoming SOS: what happened, how far, Accept / Decline with a countdown. */
export default function AlertScreen() {
  const sos = useSos();
  const offer = sos.phone?.offer ?? null;
  const [now, setNow] = useState(() => Date.now());
  const [answered, setAnswered] = useState<'accept' | 'decline' | null>(null);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, []);

  // The alert went away (taken, timed out, cancelled) without an accept: back home.
  useEffect(() => {
    if (offer || answered === 'accept') return;
    stopAlarm();
    const t = setTimeout(goHome, answered ? 0 : 1200);
    return () => clearTimeout(t);
  }, [offer, answered]);

  if (!offer) {
    return (
      <SafeAreaView style={[styles.flex, styles.closed]}>
        <Text style={styles.closedText}>{answered === 'accept' ? 'Opening directions...' : 'Alert closed'}</Text>
      </SafeAreaView>
    );
  }

  const total = Math.max(1, (offer.expires_at - offer.sent_at) / 1000);
  const left = Math.max(0, Math.ceil((offer.expires_at - (now + sos.skewMs)) / 1000));
  const me = sos.location;
  const dist = me ? distanceM(me, offer.location) : offer.distance_m;
  const dir = me ? compassWord(bearingDeg(me, offer.location)) : null;
  const fire = offer.kind === 'fire';

  return (
    <SafeAreaView style={[styles.flex, styles.bg]} edges={['top', 'bottom']}>
      <View style={styles.top}>
        <Text style={styles.kicker}>EMERGENCY NEAR YOU</Text>
        <Text style={styles.what}>{fire ? 'Fire reported' : 'Someone collapsed'}</Text>
        <Text style={styles.sub}>
          {fire ? 'A camera saw fire or smoke.' : offer.witnessed ? 'A camera saw them fall and not get up.' : 'A camera sees a person down.'}
          {!fire && offer.fire ? ' There is a fire nearby too.' : ''}
        </Text>
      </View>

      <View style={styles.middle}>
        <Beacon fire={fire} />
        <Text style={styles.distance}>{formatDistance(dist)}</Text>
        <Text style={styles.where}>
          {dir ? `to the ${dir}` : 'away'}
          {offer.place ? ` · ${offer.place}` : ''}
        </Text>
      </View>

      <View style={styles.bottom}>
        <View style={styles.track}>
          <View style={[styles.fill, { width: `${(left / total) * 100}%` }]} />
        </View>
        <Text style={styles.timer}>{left}s, then we ask the next closest person</Text>
        <Button
          title={answered === 'accept' ? 'On my way...' : "I'm going"}
          kind="white"
          icon="walk"
          disabled={answered !== null || sos.conn !== 'connected'}
          onPress={() => {
            if (accept(offer.id)) setAnswered('accept');
          }}
        />
        <Pressable
          accessibilityRole="button"
          disabled={answered !== null}
          onPress={() => {
            decline(offer.id);
            setAnswered('decline');
          }}
          style={({ pressed }) => [styles.decline, pressed && { opacity: 0.6 }]}
        >
          <Text style={styles.declineText}>{"I can't help right now"}</Text>
        </Pressable>
        {sos.conn !== 'connected' ? <Text style={styles.warn}>Reconnecting to the server...</Text> : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  bg: { backgroundColor: colors.red, paddingHorizontal: space.xl },
  closed: { alignItems: 'center', justifyContent: 'center', backgroundColor: colors.white },
  closedText: { fontFamily: font.heavy, fontSize: 20, color: colors.muted },
  top: { paddingTop: space.lg, gap: space.xs },
  kicker: { fontFamily: font.heavy, color: 'rgba(255,255,255,0.75)', letterSpacing: 2, fontSize: 13 },
  what: { fontFamily: font.black, color: colors.white, fontSize: 38, lineHeight: 42 },
  sub: { fontFamily: font.regular, color: 'rgba(255,255,255,0.9)', fontSize: 17, lineHeight: 23 },
  middle: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.xs },
  beacon: { width: 120, height: 120, alignItems: 'center', justifyContent: 'center', marginBottom: space.xl },
  ring: { position: 'absolute', width: 120, height: 120, borderRadius: 60, backgroundColor: colors.white },
  beaconCore: { width: 120, height: 120, borderRadius: 60, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  distance: { fontFamily: font.black, color: colors.white, fontSize: 76, lineHeight: 82, fontVariant: ['tabular-nums'] },
  where: { fontFamily: font.bold, color: 'rgba(255,255,255,0.9)', fontSize: 18, textAlign: 'center' },
  bottom: { gap: space.md, paddingBottom: space.lg },
  track: { height: 10, borderRadius: 5, backgroundColor: 'rgba(255,255,255,0.25)', overflow: 'hidden' },
  fill: { height: 10, borderRadius: 5, backgroundColor: colors.white },
  timer: { fontFamily: font.bold, color: 'rgba(255,255,255,0.85)', fontSize: 14, textAlign: 'center' },
  decline: { paddingVertical: space.md, alignItems: 'center' },
  declineText: { fontFamily: font.heavy, color: colors.white, fontSize: 16, letterSpacing: 0.5 },
  warn: { fontFamily: font.bold, color: '#FFE2A8', textAlign: 'center' },
});
