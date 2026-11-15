import { router } from 'expo-router';

import { postMilestone, quietly } from './api';

/**
 * "GIVE ME HELP WITH AED": tells the agent (milestone `aed_help_started`, retried quietly once,
 * never blocking) and opens the AED help screen. Without an incident (the CPR guide opened from
 * Home) nothing is sent.
 */
export function openAedHelp(incidentId: string | null | undefined, responderId: string | null | undefined, from: 'alert' | 'cpr'): void {
  if (incidentId && responderId) void quietly(() => postMilestone(incidentId, 'aed_help_started', responderId));
  router.push({ pathname: '/aed-help', params: { incidentId: incidentId ?? '', from } });
}
