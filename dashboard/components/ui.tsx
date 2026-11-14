import type { ButtonHTMLAttributes, ReactNode } from "react";
import { EMPTY } from "@/lib/copy";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Panel({
  title,
  right,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-panel", className)}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="label">{title}</h2>
          {right}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

/** A number with its unit. Missing values render as "--", never a guess. */
export function Stat({
  label,
  value,
  unit,
  note,
  tone,
  size = "md",
}: {
  label: ReactNode;
  value: string | number | null | undefined;
  unit?: string;
  note?: ReactNode;
  tone?: "red" | "yellow" | "green" | "accent" | "muted";
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const missing = value === null || value === undefined || value === "" || value === EMPTY;
  const toneClass =
    tone === "red"
      ? "text-zone-red"
      : tone === "yellow"
        ? "text-zone-yellow"
        : tone === "green"
          ? "text-zone-green"
          : tone === "accent"
            ? "text-accent"
            : tone === "muted"
              ? "text-muted"
              : "text-text";
  const sizeClass = { sm: "text-lg", md: "text-2xl", lg: "text-4xl", xl: "text-6xl" }[size];
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={cx("num mt-1 font-semibold leading-none", sizeClass, missing ? "text-faint" : toneClass)}>
        {missing ? EMPTY : value}
        {!missing && unit && <span className="ml-1 text-[0.45em] font-medium text-muted">{unit}</span>}
      </div>
      {note && <div className="mt-1.5 text-xs text-muted">{note}</div>}
    </div>
  );
}

export function Badge({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "accent" | "decision" | "red" | "yellow" | "green" | "warn" | "muted";
  className?: string;
}) {
  const tones: Record<string, string> = {
    default: "border-line-strong text-text",
    accent: "border-accent/50 text-accent bg-accent/10",
    decision: "border-decision/60 text-decision bg-decision/10",
    red: "border-zone-red/60 text-zone-red bg-zone-red/10",
    yellow: "border-zone-yellow/60 text-zone-yellow bg-zone-yellow/10",
    green: "border-zone-green/60 text-zone-green bg-zone-green/10",
    warn: "border-warn/60 text-warn bg-warn/10",
    muted: "border-line text-muted",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Button({
  tone = "default",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "default" | "primary" | "danger" | "ok" | "ghost" | "decision";
  size?: "sm" | "md" | "lg";
}) {
  const tones: Record<string, string> = {
    default: "border-line-strong bg-raised text-text hover:border-accent/60",
    primary: "border-accent bg-accent text-[#06121b] hover:brightness-110",
    danger: "border-danger bg-danger text-white hover:brightness-110",
    ok: "border-ok bg-ok text-[#06140d] hover:brightness-110",
    decision: "border-decision bg-decision text-[#1a1203] hover:brightness-110",
    ghost: "border-transparent bg-transparent text-muted hover:text-text",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm", lg: "px-5 py-3 text-base" };
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition disabled:cursor-not-allowed disabled:opacity-40",
        tones[tone],
        sizes[size],
        className,
      )}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode; disabled?: boolean }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-md border border-line bg-panel-2 p-0.5" role="group">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={o.disabled}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded px-3 font-semibold transition disabled:cursor-not-allowed disabled:opacity-35",
            size === "sm" ? "py-1 text-xs" : "py-1.5 text-sm",
            o.value === value ? "bg-raised text-text shadow-[inset_0_0_0_1px_var(--line-strong)]" : "text-muted hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-1.5 rounded-md border border-dashed border-line px-4 py-5">
      <div className="text-sm font-semibold text-text">{title}</div>
      {children && <div className="text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Dot({ tone }: { tone: "ok" | "warn" | "down" | "idle" }) {
  const c = { ok: "bg-ok", warn: "bg-zone-yellow", down: "bg-danger", idle: "bg-faint" }[tone];
  return <span className={cx("inline-block size-2 rounded-full", c)} aria-hidden />;
}
