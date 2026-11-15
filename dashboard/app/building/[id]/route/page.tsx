import { Suspense } from "react";
import { ResponderRoute } from "@/components/route/ResponderRoute";
import { EmptyState } from "@/components/ui";
import { parseGeoParam } from "@/lib/georef";
import { cleanLeg, cleanSweepId } from "@/lib/routePlan";

function one(v: string | string[] | undefined): string | null {
  const s = Array.isArray(v) ? v[0] : v;
  return typeof s === "string" && s.length > 0 && s.length <= 64 ? s : null;
}

/**
 * A responder's route in 3D: /building/{id}/route?camera=&leg=to_aed|to_person&from=<sweep>&role=&geo=<calibration>&follow=<dispatch id>
 * (opened from "View route in 3D" in the responder app).
 */
export default function ResponderRoutePage({ params, searchParams }: PageProps<"/building/[id]/route">) {
  return (
    <Suspense
      fallback={
        <div className="p-4">
          <EmptyState title="Loading the route" />
        </div>
      }
    >
      {Promise.all([params, searchParams]).then(([{ id }, sp]) => (
        <ResponderRoute
          buildingId={id}
          cameraId={cleanSweepId(sp.camera)}
          leg={cleanLeg(sp.leg)}
          from={cleanSweepId(sp.from)}
          role={one(sp.role)}
          geo={parseGeoParam(sp.geo)}
          followId={cleanSweepId(sp.follow)}
        />
      ))}
    </Suspense>
  );
}
