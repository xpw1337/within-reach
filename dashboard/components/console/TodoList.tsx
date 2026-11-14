import { cx } from "@/components/ui";
import type { Todo } from "@/lib/contracts";

export function TodoList({ todos }: { todos: Todo[] }) {
  if (todos.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  return (
    <div className="border-b border-line bg-panel-2/60 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="label">Planner plan</span>
        <span className="num text-xs text-muted">
          {done}/{todos.length} done
        </span>
      </div>
      <ol className="space-y-1.5">
        {todos.map((t, i) => (
          <li key={`${i}-${t.text}`} className="flex items-start gap-2 text-[0.82rem] leading-snug">
            <span
              aria-label={t.status}
              className={cx(
                "mt-[3px] flex size-3.5 shrink-0 items-center justify-center rounded-[4px] border",
                t.status === "done" && "border-ok bg-ok",
                t.status === "in_progress" && "border-accent",
                t.status === "pending" && "border-line-strong",
              )}
            >
              {t.status === "done" && (
                <svg viewBox="0 0 12 12" className="size-2.5 text-[#06140d]" aria-hidden>
                  <path d="M2.5 6.2 5 8.5 9.5 3.5" fill="none" stroke="currentColor" strokeWidth="2" />
                </svg>
              )}
              {t.status === "in_progress" && <span className="size-1.5 animate-pulse rounded-full bg-accent" />}
            </span>
            <span
              className={cx(
                t.status === "done" && "text-muted line-through decoration-faint",
                t.status === "in_progress" && "font-semibold text-text",
                t.status === "pending" && "text-muted",
              )}
            >
              {t.text}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
