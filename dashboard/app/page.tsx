import { EmptyState } from "@/components/ui";

export default function CityPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">City map</h1>
      <div className="mt-4">
        <EmptyState title="--">The city map lands in subtask 3.5.</EmptyState>
      </div>
    </div>
  );
}
