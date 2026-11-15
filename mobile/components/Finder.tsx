import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';

/**
 * Precision-finding visual (after Apple's Find My): a big arrow that points where to walk, an arc
 * from straight ahead to that direction showing how far to turn, and a dot that swells when you
 * face the target. Close by, the arrow gives way to a breathing disc.
 *
 * ``rel`` is the target's direction relative to where the phone points, -180..180 (right positive),
 * or null when the phone has no compass.
 */
export function Finder({ rel, color, near, size = 300 }: { rel: number | null; color: string; near: boolean; size?: number }) {
  const angle = rel ?? 0;
  const ahead = rel !== null && Math.abs(rel) < 20;
  const [rot] = useState(() => new Animated.Value(angle));
  const last = useRef<number | null>(null);
  const [breath] = useState(() => new Animated.Value(0));

  useEffect(() => {
    let target = angle;
    const prev = last.current ?? angle;
    while (target - prev > 180) target -= 360;
    while (target - prev < -180) target += 360;
    last.current = target;
    Animated.timing(rot, { toValue: target, duration: 220, easing: Easing.out(Easing.quad), useNativeDriver: true }).start();
  }, [angle, rot]);

  useEffect(() => {
    if (!near) return;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(breath, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(breath, { toValue: 0, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [near, breath]);

  const r = size / 2 - 12;
  const c = size / 2;
  const point = (deg: number) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [c + r * Math.cos(a), c + r * Math.sin(a)];
  };
  // Arc from straight ahead (12 o'clock) round to the target direction.
  const sweep = Math.max(-179.9, Math.min(179.9, angle));
  const [sx, sy] = point(0);
  const [ex, ey] = point(sweep);
  const arc = `M ${sx} ${sy} A ${r} ${r} 0 ${Math.abs(sweep) > 180 ? 1 : 0} ${sweep >= 0 ? 1 : 0} ${ex} ${ey}`;
  const spin = rot.interpolate({ inputRange: [-3600, 3600], outputRange: ['-3600deg', '3600deg'] });

  if (near) {
    return (
      <View style={[styles.box, { width: size, height: size }]}>
        <Animated.View
          style={[styles.disc, {
            width: size * 0.62, height: size * 0.62, borderRadius: size * 0.31, backgroundColor: color,
            transform: [{ scale: breath.interpolate({ inputRange: [0, 1], outputRange: [0.86, 1.04] }) }],
            opacity: breath.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1] }),
          }]}
        />
      </View>
    );
  }

  return (
    <View style={[styles.box, { width: size, height: size }]}>
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        {!ahead && rel !== null ? (
          <>
            <Path d={arc} stroke={color} strokeWidth={14} strokeLinecap="round" fill="none" opacity={0.9} />
            <Circle cx={ex} cy={ey} r={9} fill={color} />
          </>
        ) : null}
        <Circle cx={sx} cy={sy} r={ahead ? 14 : 8} fill={ahead ? color : '#BDBDBD'} />
      </Svg>
      <Animated.View style={{ transform: [{ rotate: spin }] }}>
        <Svg width={size * 0.56} height={size * 0.56} viewBox="0 0 100 100">
          <Path
            d="M50 6 L86 46 Q89 50 84 52 L62 52 L62 90 Q62 95 57 95 L43 95 Q38 95 38 90 L38 52 L16 52 Q11 50 14 46 Z"
            fill={rel === null ? '#BDBDBD' : color}
          />
        </Svg>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { alignItems: 'center', justifyContent: 'center' },
  disc: {},
});
