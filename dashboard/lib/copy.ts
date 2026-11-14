// Fixed wording. User-facing text about missing equipment, approximations and
// estimates comes from here only (docs/ARCHITECTURE.md section 8), so it
// cannot drift between pages.
import type { GapType } from "./rows";

export const EMPTY = "--";

const NAMES: Record<string, { one: string; title: string; plural: string }> = {
  aed: { one: "AED", title: "AED", plural: "AEDs" },
  extinguisher: { one: "extinguisher", title: "Extinguisher", plural: "extinguishers" },
  exit: { one: "exit", title: "Exit", plural: "exits" },
  exit_sign: { one: "exit sign", title: "Exit sign", plural: "exit signs" },
  naloxone: { one: "naloxone kit", title: "Naloxone", plural: "naloxone kits" },
  sprinkler: { one: "sprinkler", title: "Sprinkler", plural: "sprinklers" },
  smoke_detector: { one: "smoke detector", title: "Smoke detector", plural: "smoke detectors" },
  first_aid: { one: "first aid kit", title: "First aid", plural: "first aid kits" },
  stairs: { one: "stairs", title: "Stairs", plural: "stairs" },
  elevator: { one: "elevator", title: "Elevator", plural: "elevators" },
};

export function assetName(type: string | null | undefined): string {
  return (type && NAMES[type]?.one) || type || "equipment";
}
export function assetTitle(type: string | null | undefined): string {
  return (type && NAMES[type]?.title) || type || "Equipment";
}
export function assetPlural(type: string | null | undefined): string {
  return (type && NAMES[type]?.plural) || type || "equipment";
}

/** Never "no AED": only what the scan shows (spec rule 4). */
export function noneVisible(type: string): string {
  return `No ${assetName(type)} visible in the scan`;
}

export const copy = {
  noneVisible,
  visibleInScan: "visible in the scan",
  approximation:
    "Thresholds are approximations: unverified defaults from the census config (spec section 20), not a code compliance finding.",
  approximationShort: "Approximate thresholds",
  thresholdsUnavailable:
    "Thresholds unavailable: the agent API is not reachable, so zones are shown as unknown.",
  unknownZone: (type: GapType) => `Unknown: no ${assetName(type)} visible in the scan, or unreachable on the scan graph`,
  notMapped: "Not mapped yet",
  redShareOfPositions: "of scanned positions",
  peopleAtRiskEstimate: "people at risk (estimate)",
  occupancyEstimate: "occupancy (estimate)",
  ownerLetterDraft: "Draft for the owner. Never sent automatically.",
  stairsOnly: "Stairs-only route from an upper floor",
  blockedExits: (n: number) => (n === 1 ? "1 exit looks blocked" : `${n} exits look blocked`),
  fixtureTag: "demo fixture, not counted",
  supabaseMissing: "Supabase is not configured (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY).",
  agentMissing: "Agent API is not configured (NEXT_PUBLIC_AGENT_URL).",
  agentUnreachable: "Agent API is not reachable.",
  noRun: "No census run yet.",
  personDown: "Person down",
  possibleCardiac: "Possible cardiac arrest",
  fall: "Fall, responsive",
  foundDownTimeUnknown: "Found down, time unknown",
  matterportHidden: "3D twin hidden: no Matterport SDK key or model id for this building.",
};
