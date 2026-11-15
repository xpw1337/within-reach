import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { startAlarm, stopAlarm } from './alarm';
import { effectiveServerUrl, settingsStore, useSettings, wsUrl } from './settings';
import { createStore, useStore } from './store';
import type { LatLng, PhoneState } from './types';

// One websocket to the agent (/sos/ws/phone) for the whole app: it carries this phone's location,
// duty status and answers, and brings back alerts and directions. Reconnects on its own.

export type Conn = 'off' | 'connecting' | 'connected' | 'error';

type SosState = {
  conn: Conn;
  error: string | null;
  server: string;
  phone: PhoneState | null;
  /** Clock offset: server time minus phone time, ms (for the accept countdown). */
  skewMs: number;
  location: (LatLng & { accuracy_m: number | null; at: number }) | null;
  locationStatus: 'idle' | 'asking' | 'denied' | 'watching' | 'error';
  heading: number | null;
  lastResult: { action: string; ok: boolean; reason?: string } | null;
};

export const sosStore = createStore<SosState>({
  conn: 'off',
  error: null,
  server: '',
  phone: null,
  skewMs: 0,
  location: null,
  locationStatus: 'idle',
  heading: null,
  lastResult: null,
});

export function useSos(): SosState {
  return useStore(sosStore);
}

let socket: WebSocket | null = null;
/** Reconnect the live socket now (set while connected). */
const connection: { restart: (() => void) | null } = { restart: null };

export function send(msg: Record<string, unknown>): boolean {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(msg));
    return true;
  }
  return false;
}

export function accept(offerId: string): boolean {
  stopAlarm();
  return send({ type: 'accept', offer_id: offerId });
}

export function decline(offerId: string): boolean {
  stopAlarm();
  return send({ type: 'decline', offer_id: offerId });
}

export function arrived(): boolean {
  return send({ type: 'arrived' });
}

let lastOfferId: string | null = null;
let lastMissionId: string | null = null;

/** Moves between screens and runs the alarm as the server state changes. */
function onPhoneState(p: PhoneState): void {
  const offer = p.offer;
  if (offer && offer.id !== lastOfferId) {
    lastOfferId = offer.id;
    void startAlarm();
    router.push('/alert');
  }
  if (!offer && lastOfferId) {
    lastOfferId = null;
    stopAlarm();
  }
  const mission = p.mission;
  if (mission && mission.status !== 'resolved' && mission.id !== lastMissionId) {
    lastMissionId = mission.id;
    stopAlarm();
    router.replace('/mission');
  }
  if (!mission) lastMissionId = null;
}

function connect(): () => void {
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let ping: ReturnType<typeof setInterval> | null = null;
  let delay = 1000;
  let lastMessageAt = Date.now();

  // A socket that died while the app was in the background may never report it: the server
  // answers every ping, so silence for this long means the connection is gone.
  const watchdog = setInterval(() => {
    const ws = socket;
    if (closed || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (Date.now() - lastMessageAt > 25000) restart();
  }, 5000);

  const restart = () => {
    const ws = socket;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      try {
        ws.close();
      } catch {
        // already gone
      }
    }
    socket = null;
    if (ping) clearInterval(ping);
    if (retry) clearTimeout(retry);
    if (!closed) open();
  };

  const open = () => {
    const { settings } = settingsStore.get();
    const server = effectiveServerUrl(settings);
    sosStore.set((s) => ({ ...s, server }));
    if (!server) {
      sosStore.set((s) => ({ ...s, conn: 'error', error: 'No server set. Enter the laptop address below.' }));
      return;
    }
    sosStore.set((s) => ({ ...s, conn: 'connecting', error: null }));
    const ws = new WebSocket(wsUrl(server, '/sos/ws/phone'));
    socket = ws;
    ws.onopen = () => {
      delay = 1000;
      lastMessageAt = Date.now();
      const loc = sosStore.get().location;
      const { settings: st } = settingsStore.get();
      ws.send(JSON.stringify({
        type: 'hello', id: st.id, name: st.name || 'Responder', on_duty: st.onDuty, phone: st.phone,
        ...(loc ? { lat: loc.lat, lng: loc.lng, accuracy_m: loc.accuracy_m } : {}),
      }));
      sosStore.set((s) => ({ ...s, conn: 'connected', error: null }));
      if (ping) clearInterval(ping);
      ping = setInterval(() => send({ type: 'ping' }), 10000);
    };
    ws.onmessage = (ev) => {
      lastMessageAt = Date.now();
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(String(ev.data));
      } catch {
        return;
      }
      if (msg.type === 'state') {
        const phone = msg as unknown as PhoneState;
        sosStore.set((s) => ({ ...s, phone, skewMs: phone.server_time - Date.now() }));
        onPhoneState(phone);
      } else if (msg.type === 'result') {
        sosStore.set((s) => ({ ...s, lastResult: msg as SosState['lastResult'] }));
      }
    };
    ws.onerror = () => {
      sosStore.set((s) => ({ ...s, error: `Can't reach ${server}` }));
    };
    ws.onclose = () => {
      if (ping) clearInterval(ping);
      if (socket === ws) socket = null;
      if (closed) return;
      sosStore.set((s) => ({ ...s, conn: 'error' }));
      retry = setTimeout(open, delay);
      delay = Math.min(delay * 2, 8000);
    };
  };

  open();
  connection.restart = restart;
  return () => {
    closed = true;
    clearInterval(watchdog);
    if (retry) clearTimeout(retry);
    if (ping) clearInterval(ping);
    socket?.close();
    socket = null;
    sosStore.set((s) => ({ ...s, conn: 'off' }));
  };
}

/** Root hook: keeps the socket open while the app is in the foreground. Reconnects on server change. */
export function useSosConnection(): void {
  const { ready, settings } = useSettings();
  const server = effectiveServerUrl(settings);
  useEffect(() => {
    if (!ready) return;
    let stop = connect();
    // Back in the foreground: iOS has usually killed the socket, so always start a fresh one.
    const sub = AppState.addEventListener('change', (st) => {
      if (st === 'active') {
        if (connection.restart) connection.restart();
        else {
          stop();
          stop = connect();
        }
      }
    });
    return () => {
      sub.remove();
      stop();
    };
  }, [ready, server]);

  // Duty and name changes go out on the open socket.
  useEffect(() => {
    if (ready) send({ type: 'duty', on_duty: settings.onDuty, name: settings.name || 'Responder', phone: settings.phone });
  }, [ready, settings.onDuty, settings.name, settings.phone]);
}

/** Root hook: watches GPS while on duty or on a mission and sends it to the agent. */
export function useLocationReporter(): void {
  const { ready, settings } = useSettings();
  const onMission = Boolean(useSos().phone?.mission);
  const active = ready && settings.onboarded && (settings.onDuty || onMission);
  useEffect(() => {
    if (!active) return;
    let sub: Location.LocationSubscription | null = null;
    let headingSub: Location.LocationSubscription | null = null;
    let cancelled = false;
    (async () => {
      sosStore.set((s) => ({ ...s, locationStatus: 'asking' }));
      const perm = await Location.requestForegroundPermissionsAsync();
      if (cancelled) return;
      if (perm.status !== 'granted') {
        sosStore.set((s) => ({ ...s, locationStatus: 'denied' }));
        return;
      }
      try {
        sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.BestForNavigation, distanceInterval: 2, timeInterval: 2000 },
          (pos) => {
            const loc = {
              lat: pos.coords.latitude,
              lng: pos.coords.longitude,
              accuracy_m: pos.coords.accuracy ?? null,
              at: pos.timestamp,
            };
            sosStore.set((s) => ({ ...s, location: loc, locationStatus: 'watching' }));
            send({ type: 'location', lat: loc.lat, lng: loc.lng, accuracy_m: loc.accuracy_m });
          },
        );
        headingSub = await Location.watchHeadingAsync((h) => {
          const heading = h.trueHeading >= 0 ? h.trueHeading : h.magHeading;
          sosStore.set((s) => ({ ...s, heading }));
        });
      } catch {
        sosStore.set((s) => ({ ...s, locationStatus: 'error' }));
      }
    })();
    return () => {
      cancelled = true;
      sub?.remove();
      headingSub?.remove();
    };
  }, [active]);
}
