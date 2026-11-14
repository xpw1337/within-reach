import AsyncStorage from '@react-native-async-storage/async-storage';

import { createStore, useStore } from './store';
import { requireSupabase } from './supabase';
import type { ResponderRole } from './types';

/** The responder's own profile, kept on the phone and mirrored to their `responders` row. */
export type Profile = {
  id: string;
  name: string;
  phone: string;
  cpr_trained: boolean;
  role: ResponderRole;
  building_id: string | null;
  /** Display name of the chosen building, local only. */
  building_label: string | null;
  consent_location: boolean;
  consent_calls: boolean;
  on_duty: boolean;
};

export type ProfileInput = Omit<Profile, 'id' | 'on_duty'>;

const STORAGE_KEY = 'within-reach.profile.v1';

type ProfileState = { ready: boolean; profile: Profile | null; loadError: string | null };

export const profileStore = createStore<ProfileState>({ ready: false, profile: null, loadError: null });

export function useProfile(): ProfileState {
  return useStore(profileStore);
}

function isProfile(value: unknown): value is Profile {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === 'string' && typeof v.name === 'string' && typeof v.phone === 'string';
}

export async function loadProfile(): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    profileStore.set({ ready: true, profile: isProfile(parsed) ? parsed : null, loadError: null });
  } catch (error) {
    profileStore.set({ ready: true, profile: null, loadError: String(error) });
  }
}

async function persist(profile: Profile): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
  profileStore.set((s) => ({ ...s, profile }));
}

/** Digits-only check that the typed number is plausible. The number itself is never logged. */
export function isPlausiblePhone(phone: string): boolean {
  const trimmed = phone.trim();
  if (!/^[+\d\s().-]+$/.test(trimmed)) return false;
  const digits = trimmed.replace(/\D/g, '');
  return digits.length >= 7 && digits.length <= 15;
}

/** Spellings a stored number might use: as typed, digits only, E.164, and +1 for 10-digit US numbers. */
function phoneCandidates(phone: string): string[] {
  const digits = phone.replace(/\D/g, '');
  const set = new Set([phone.trim(), digits, `+${digits}`]);
  if (digits.length === 10) set.add(`+1${digits}`);
  return [...set].filter(Boolean);
}

/** An existing responders row with the same phone number (for example a seeded teammate), if any. */
async function findResponderIdByPhone(phone: string): Promise<string | null> {
  const digits = phone.replace(/\D/g, '');
  const { data, error } = await requireSupabase().from('responders').select('id,phone').in('phone', phoneCandidates(phone)).limit(5);
  if (error) throw error;
  const rows = (data ?? []) as { id: string; phone: string }[];
  const same = (p: string) => {
    const d = p.replace(/\D/g, '');
    return d === digits || (digits.length === 10 && d === `1${digits}`) || (d.length === 10 && digits === `1${d}`);
  };
  return rows.find((r) => same(r.phone))?.id ?? null;
}

/**
 * Saves this responder's row and stores its id locally. `callable` is never written here: only
 * seeded teammates are callable (the agent's telephony allowlist relies on that).
 * - Later saves update the row whose id is stored on the phone.
 * - First save: if a row with the same phone number exists (a seeded teammate), adopt its id and
 *   update only the profile and consent fields, keeping its stored phone spelling, so that phone
 *   alarms and rings as one responder. Otherwise insert a new row and let the database assign the id.
 */
export async function saveProfile(input: ProfileInput): Promise<Profile> {
  const existing = profileStore.get().profile;
  const onDuty = existing?.on_duty ?? true;
  const sb = requireSupabase();
  const fields: Record<string, unknown> = {
    name: input.name.trim(),
    cpr_trained: input.cpr_trained,
    role: input.role,
    building_id: input.building_id,
    consent_location: input.consent_location,
    consent_calls: input.consent_calls,
    on_duty: onDuty,
  };

  let id: string | null = null;
  const adoptId = existing?.id ? null : await findResponderIdByPhone(input.phone);
  if (adoptId) {
    const { error } = await sb.from('responders').update(fields).eq('id', adoptId);
    if (error) throw error;
    id = adoptId;
  } else {
    const row: Record<string, unknown> = { ...fields, phone: input.phone.trim() };
    if (existing?.id) row.id = existing.id;
    const { data, error } = await sb.from('responders').upsert(row).select('id').single();
    if (error) throw error;
    id = (data as { id: string } | null)?.id ?? null;
  }
  if (!id) throw new Error('The database did not return a responder id.');

  const profile: Profile = { ...input, name: input.name.trim(), phone: input.phone.trim(), id, on_duty: onDuty };
  await persist(profile);
  return profile;
}

/** Updates `responders.on_duty`, optimistic locally, reverted if the write fails. */
export async function setOnDuty(onDuty: boolean): Promise<void> {
  const current = profileStore.get().profile;
  if (!current) return;
  await persist({ ...current, on_duty: onDuty });
  const { error } = await requireSupabase().from('responders').update({ on_duty: onDuty }).eq('id', current.id);
  if (error) {
    await persist({ ...current, on_duty: current.on_duty });
    throw error;
  }
}

/** Forgets the local profile (the database row is left as is). */
export async function clearProfile(): Promise<void> {
  await AsyncStorage.removeItem(STORAGE_KEY);
  profileStore.set((s) => ({ ...s, profile: null }));
}
