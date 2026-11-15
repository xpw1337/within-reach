// Agent API calls the app makes, per docs/CONTRACTS.md section 2 ("Live").
// Every command is idempotent on the server, so a retry is always safe.

import { env } from './env';
import type { DispatchStatus } from './types';

const TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  if (!env.agentUrl) {
    throw new ApiError('EXPO_PUBLIC_AGENT_URL is not set in this build.', null);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${env.agentUrl}${path}`, {
      method: 'POST',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === 'AbortError';
    throw new ApiError(aborted ? 'The agent did not answer in time.' : 'Could not reach the agent.', null);
  } finally {
    clearTimeout(timer);
  }

  const text = await response.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  if (!response.ok) {
    const detail =
      json && typeof json === 'object' && 'detail' in json ? String((json as { detail: unknown }).detail) : `HTTP ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return json as T;
}

/**
 * `{role, status}`, or `{status: "released"}` when both roles are already taken. With an AED route
 * mapped, the first non-staff accept is `aed_runner` and the second `patient`; staff keep `staff`.
 */
export type AcceptResponse = { role?: 'patient' | 'aed_runner' | 'staff'; status: DispatchStatus };

export function acceptDispatch(dispatchId: string): Promise<AcceptResponse> {
  return post<AcceptResponse>(`/dispatches/${encodeURIComponent(dispatchId)}/accept`);
}

export function declineDispatch(dispatchId: string): Promise<{ status: DispatchStatus }> {
  return post<{ status: DispatchStatus }>(`/dispatches/${encodeURIComponent(dispatchId)}/decline`);
}

export function arrivedDispatch(dispatchId: string, withAed: boolean): Promise<{ status: DispatchStatus }> {
  return post<{ status: DispatchStatus }>(`/dispatches/${encodeURIComponent(dispatchId)}/arrived`, { with_aed: withAed });
}

/** Milestones the responder app reports (the agent also accepts cpr_started, aed_arrived, responder_arrived). */
export type MilestoneKind = 'aed_picked_up' | 'aed_help_started';

export function postMilestone(incidentId: string, kind: MilestoneKind, by: string): Promise<{ ok: boolean }> {
  return post<{ ok: boolean }>(`/incidents/${encodeURIComponent(incidentId)}/milestone`, { kind, by });
}

const QUIET_RETRY_MS = 2_000;

/**
 * Runs a command that must never block the screen: on failure it retries once after a short wait,
 * then gives up silently. Resolves with the result, or null if both tries failed. Safe because every
 * command is idempotent on the server.
 */
export async function quietly<T>(call: () => Promise<T>): Promise<T | null> {
  try {
    return await call();
  } catch {
    await new Promise((resolve) => setTimeout(resolve, QUIET_RETRY_MS));
    try {
      return await call();
    } catch {
      return null;
    }
  }
}
