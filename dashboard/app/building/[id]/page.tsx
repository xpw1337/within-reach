import { Suspense } from "react";
import { BuildingView } from "@/components/building/BuildingView";
import { EmptyState } from "@/components/ui";

export default function BuildingPage({ params }: PageProps<"/building/[id]">) {
  return (
    <Suspense
      fallback={
        <div className="p-6">
          <EmptyState title="Loading building" />
        </div>
      }
    >
      {params.then(({ id }) => (
        <BuildingView id={id} />
      ))}
    </Suspense>
  );
}
