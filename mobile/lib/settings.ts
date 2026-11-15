import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';

import { createStore, useStore } from './store';

// Everything the phone needs, kept on the phone: an id, a display name, duty status and the agent
// URL. Nothing is hard-coded: the agent URL is, in order, what the user typed, EXPO_PUBLIC_AGENT_URL,
// or the laptop that serves this app in Expo Go (same host, port 8000).

const KEY = 'within-reach:settings:v2';

export type Settings = {
  id: string;
  name: string;
  onDuty: boolean;
  serverUrl: string; // empty = automatic
  phone: string; // as typed; the agent normalizes it. Used only to ring this phone for an alert.
  onboarded: boolean;
};

type State = { ready: boolean; settings: Settings };

function newId(): string {
  const rnd = () => Math.random().toString(36).slice(2, 10);
  return `p-${Date.now().toString(36)}-${rnd()}`;
}

export const settingsStore = createStore<State>({
  ready: false,
  settings: { id: '', name: '', onDuty: true, serverUrl: '', phone: '', onboarded: false },
});

export function useSettings(): State {
  return useStore(settingsStore);
}

export async function loadSettings(): Promise<void> {
  let saved: Partial<Settings> = {};
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) saved = JSON.parse(raw) as Partial<Settings>;
  } catch {
    // First run or unreadable: start fresh.
  }
  const settings: Settings = {
    id: saved.id || newId(),
    name: saved.name ?? '',
    onDuty: saved.onDuty ?? true,
    serverUrl: saved.serverUrl ?? '',
    phone: saved.phone ?? '',
    onboarded: saved.onboarded ?? false,
  };
  settingsStore.set({ ready: true, settings });
  if (!saved.id) await persist(settings);
}

async function persist(s: Settings): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // Not fatal: the values still apply for this session.
  }
}

export async function updateSettings(patch: Partial<Settings>): Promise<void> {
  const next = { ...settingsStore.get().settings, ...patch };
  settingsStore.set((st) => ({ ...st, settings: next }));
  await persist(next);
}

function clean(url: string): string {
  let u = url.trim().replace(/\/+$/, '');
  if (u && !/^https?:\/\//i.test(u)) u = `http://${u}`;
  return u;
}

/** The agent URL detected without user input, or '' if none. */
export function automaticServerUrl(): string {
  const fromEnv = clean(process.env.EXPO_PUBLIC_AGENT_URL ?? '');
  if (fromEnv) return fromEnv;
  // In Expo Go, hostUri is "<laptop LAN IP>:<metro port>": the agent runs on the same laptop.
  const hostUri = Constants.expoConfig?.hostUri ?? '';
  const host = hostUri.split(':')[0];
  if (host && host !== 'localhost' && !host.endsWith('.exp.direct')) return `http://${host}:8000`;
  return '';
}

export function effectiveServerUrl(s: Settings): string {
  return clean(s.serverUrl) || automaticServerUrl();
}

export function wsUrl(httpUrl: string, path: string): string {
  return httpUrl.replace(/^http/i, 'ws') + path;
}
