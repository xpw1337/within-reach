import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { startAlarm, stopAlarm } from './alarm';
import { createStore, useStore } from './store';
import { errorMessage, supabase } from './supabase';
import type { DispatchRow, IncidentStatus } from './types';

/** Accept window from sent_at (spec 9.10: 20 s timeout). The agent marks the timeout itself. */
export const ACCEPT_TIMEOUT_S = 20;

export type RealtimeStatus = 'off' | 'connecting' | 'connected' | 'error';

type AlertState = {
  /** The one alert being handled. A second dispatch while this one is open is ignored. */
  dispatch: DispatchRow | null;
  realtime: RealtimeStatus;
  realtimeError: string | null;
};

export const alertStore = createStore<AlertState>({ dispatch: null, realtime: 'off', realtimeError: null });

export function useAlertState(): AlertState {
  return useStore(alertStore);
}

export function isOpen(d: DispatchRow | null): boolean {
  return d !== null && (d.status === 'sent' || d.status === 'accepted');
}

/** Seconds left to answer, clamped to [0, 20] so a phone clock ahead of or behind the server stays sane. */
export function secondsLeft(d: Pick<DispatchRow, 'sent_at'>, nowMs: number = Date.now()): number {
  const sent = Date.parse(d.sent_at);
  if (Number.isNaN(sent)) return 0;
  return Math.max(0, Math.min(ACCEPT_TIMEOUT_S, ACCEPT_TIMEOUT_S - (nowMs - sent) / 1000));
}

function goHome() {
  if (router.canDismiss()) router.dismissTo('/');
  else router.replace('/');
}

/** Ends the current alert locally (countdown ran out, or the user is done). */
export function closeAlert(): void {
  stopAlarm();
  alertStore.set((s) => ({ ...s, dispatch: null }));
}

/**
 * Single entry point for every dispatch change: Realtime rows, refetches and API responses.
 * Starts the alarm for a new alert, stops it on any answer, and moves between screens.
 */
export function applyDispatch(row: DispatchRow): void {
  const current = alertStore.get().dispatch;

  if (!current || current.id !== row.id) {
    if (isOpen(current)) return; // one alert at a time
    const fresh = row.status === 'sent' && secondsLeft(row) > 0;
    if (!fresh && row.status !== 'accepted') return; // stale or already answered
    alertStore.set((s) => ({ ...s, dispatch: row }));
    if (fresh) void startAlarm();
    router.push({ pathname: '/alert/[dispatchId]', params: { dispatchId: row.id } });
    return;
  }

  const previous = current.status;
  const merged: DispatchRow = { ...current, ...row };
  alertStore.set((s) => ({ ...s, dispatch: merged }));
  if (merged.status !== 'sent') stopAlarm();
  if (merged.status === previous) return;

  if (merged.status === 'released') {
    router.replace('/released');
  } else if (merged.status === 'timeout' || merged.status === 'declined') {
    closeAlert();
    goHome();
  }
}

/** Patch from an API response for the current dispatch. */
export function patchDispatch(id: string, patch: Partial<DispatchRow>): void {
  const current = alertStore.get().dispatch;
  if (!current || current.id !== id) return;
  applyDispatch({ ...current, ...patch });
}

const CLOSED_INCIDENT: IncidentStatus[] = ['resolved', 'false_alarm'];

/** Finds an open dispatch for me (missed while the socket was down) and applies it. */
async function refetchOpen(responderId: string): Promise<void> {
  if (!supabase) return;
  const { data, error } = await supabase
    .from('dispatches')
    .select('*')
    .eq('responder_id', responderId)
    .in('status', ['sent', 'accepted'])
    .order('sent_at', { ascending: false })
    .limit(5);
  if (error) return;
  const rows = (data ?? []) as DispatchRow[];

  // The current alert may have changed or been deleted (POST /reset) while we were away.
  const current = alertStore.get().dispatch;
  if (current && isOpen(current)) {
    const same = rows.find((r) => r.id === current.id);
    if (same) {
      applyDispatch(same);
      return;
    }
    const { data: fresh } = await supabase.from('dispatches').select('*').eq('id', current.id).maybeSingle();
    if (fresh) applyDispatch(fresh as DispatchRow);
    else {
      closeAlert();
      goHome();
    }
    return;
  }

  for (const row of rows) {
    if (row.status === 'sent' && secondsLeft(row) <= 0) continue;
    if (row.incident_id) {
      const { data: incident } = await supabase.from('incidents').select('status').eq('id', row.incident_id).maybeSingle();
      const status = (incident as { status: IncidentStatus } | null)?.status;
      if (!status || CLOSED_INCIDENT.includes(status)) continue;
    }
    applyDispatch(row);
    return;
  }
}

/**
 * Realtime subscription to dispatches for this responder (docs/CONTRACTS.md section 3, "Mobile
 * subscription"), plus a refetch whenever the channel (re)joins or the app returns to the
 * foreground, so an alert sent while the socket was down is not lost.
 */
export function useDispatchWatcher(responderId: string | null): void {
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!responderId || !supabase) {
      alertStore.set((s) => ({ ...s, realtime: 'off', realtimeError: null }));
      return;
    }
    const sb = supabase;
    let active = true;
    alertStore.set((s) => ({ ...s, realtime: 'connecting', realtimeError: null }));

    const channel = sb
      .channel(`dispatches-${responderId}-${generation}`)
      .on<DispatchRow>(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'dispatches', filter: `responder_id=eq.${responderId}` },
        (payload) => {
          if (!active) return;
          if (payload.eventType === 'DELETE') {
            const goneId = (payload.old as Partial<DispatchRow>).id;
            const current = alertStore.get().dispatch;
            if (goneId && current?.id === goneId) {
              closeAlert();
              goHome();
            }
            return;
          }
          applyDispatch(payload.new);
        },
      )
      .subscribe((status, err) => {
        if (!active) return;
        if (status === 'SUBSCRIBED') {
          alertStore.set((s) => ({ ...s, realtime: 'connected', realtimeError: null }));
          void refetchOpen(responderId);
        } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
          alertStore.set((s) => ({ ...s, realtime: 'error', realtimeError: err ? errorMessage(err) : status }));
        } else if (status === 'CLOSED') {
          alertStore.set((s) => ({ ...s, realtime: 'off' }));
        }
      });

    const appStateSub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') return;
      if (alertStore.get().realtime !== 'connected') setGeneration((g) => g + 1); // resubscribe
      else void refetchOpen(responderId);
    });

    return () => {
      active = false;
      appStateSub.remove();
      void sb.removeChannel(channel);
    };
  }, [responderId, generation]);
}

/** Loads one dispatch by id (deep link or app restart) and adopts it if it is mine. */
export async function adoptDispatch(dispatchId: string, responderId: string): Promise<DispatchRow | null> {
  if (!supabase) return null;
  const { data } = await supabase.from('dispatches').select('*').eq('id', dispatchId).maybeSingle();
  const row = data as DispatchRow | null;
  if (!row || row.responder_id !== responderId) return null;
  const live = (row.status === 'sent' && secondsLeft(row) > 0) || row.status === 'accepted' || row.status === 'arrived';
  if (!live) return null;
  const current = alertStore.get().dispatch;
  if (!current || current.id !== row.id) {
    if (isOpen(current)) return null;
    alertStore.set((s) => ({ ...s, dispatch: row }));
    if (row.status === 'sent' && secondsLeft(row) > 0) void startAlarm();
  }
  return row;
}
