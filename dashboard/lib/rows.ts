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

/** The fallback building is a fixture: never counted in a headline (demo/DESIGN.md). */
export function isFixture(b: Pick<Building, "costar_property_id"> | null | undefined): boolean {
  return Boolean(b?.costar_property_id?.startsWith("FALLBACK-"));
}
