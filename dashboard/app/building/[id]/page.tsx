import { Suspense } from "react";
import { EmptyState } from "@/components/ui";

export default function BuildingPage({ params }: PageProps<"/building/[id]">) {
  return (
    <div className="p-6">
      <Suspense fallback={<EmptyState title="--">Loading building</EmptyState>}>
        {params.then(({ id }) => (
          <EmptyState title={`Building ${id}`}>The building page lands in subtask 3.3.</EmptyState>
        ))}
      </Suspense>
    </div>
  );
}
