// Row aliases derived from the generated schema types (lib/types.ts).
import type { Enums, Tables } from "./types";

export type Building = Tables<"buildings">;
export type TwinNode = Tables<"twin_nodes">;
export type Asset = Tables<"assets">;
export type Coverage = Tables<"coverage">;
export type BuildingScore = Tables<"building_scores">;
export type Fix = Tables<"fixes">;
export type DocumentRow = Tables<"documents">;
export type Run = Tables<"runs">;
export type AgentEvent = Tables<"agent_events">;
export type Detection = Tables<"detections">;
export type Camera = Tables<"cameras">;
export type CameraRoute = Tables<"camera_routes">;
export type Responder = Tables<"responders">;
export type Incident = Tables<"incidents">;
export type IncidentEvent = Tables<"incident_events">;
export type Dispatch = Tables<"dispatches">;

export type AssetType = Enums<"asset_type">;
export type IncidentStatus = Enums<"incident_status">;
export type DispatchStatus = Enums<"dispatch_status">;
export type DispatchRole = Enums<"dispatch_role">;

/** The three equipment types the census measures (spec section 9.4). */
export type GapType = "aed" | "extinguisher" | "exit";
export const GAP_TYPES: GapType[] = ["aed", "extinguisher", "exit"];

/** Tables in the supabase_realtime publication (0001_init.sql). */
export type PublishedTable =
  | "agent_events"
  | "runs"
  | "building_scores"
  | "incidents"
  | "incident_events"
  | "dispatches"
  | "responders";

/**
 * Buildings that are not census buildings, by costar_property_id prefix:
 * FALLBACK- is the hand-built fixture (demo/DESIGN.md), DEMO- is the live demo
 * venue (docs/NEXT.md). Neither is ever counted in a headline, ranking, city
 * map or run progress; both stay reachable by direct link.
 */
export const NON_CENSUS_PREFIXES = { "FALLBACK-": "fixture", "DEMO-": "demo" } as const;
export type NonCensusKind = (typeof NON_CENSUS_PREFIXES)[keyof typeof NON_CENSUS_PREFIXES];

export function nonCensusKind(b: Pick<Building, "costar_property_id"> | null | undefined): NonCensusKind | null {
  const id = b?.costar_property_id;
  if (!id) return null;
  for (const [prefix, kind] of Object.entries(NON_CENSUS_PREFIXES)) {
    if (id.startsWith(prefix)) return kind;
  }
  return null;
}

/** The one exclusion check for census numbers (fixture and demo buildings). */
export function isExcludedFromCensus(b: Pick<Building, "costar_property_id"> | null | undefined): boolean {
  return nonCensusKind(b) !== null;
}

/** PostgREST `or` filter matching every excluded building, built from the same prefixes. */
export function nonCensusFilter(): string {
  return Object.keys(NON_CENSUS_PREFIXES)
    .map((p) => `costar_property_id.like.${p}*`)
    .join(",");
}

/**
 * A run counts toward run progress unless it only touched excluded buildings
 * (a stage rerun of the demo or fixture building). Unknown ids count, so a
 * census run is never hidden by missing data.
 */
export function isCensusRun(buildingIds: string[], excludedIds: ReadonlySet<string>): boolean {
  if (buildingIds.length === 0) return true;
  return !buildingIds.every((id) => excludedIds.has(id));
}

/** A disclosed demo prop placed by the team (flags contains 'simulated'), never a census finding. */
export function isSimulated(a: { flags?: Asset["flags"] } | null | undefined): boolean {
  return Boolean(a?.flags?.includes("simulated"));
}
