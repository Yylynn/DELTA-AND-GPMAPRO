import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-heading-actions">{actions}</div>}
    </header>
  );
}

export function PanelHeading({
  title,
  description,
  meta,
  icon,
}: {
  title: string;
  description?: string;
  meta?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div className="panel-heading-copy">
        <div className="panel-heading-title">
          {icon}
          {title}
        </div>
        {description && <p>{description}</p>}
      </div>
      {meta && <div className="panel-heading-meta">{meta}</div>}
    </div>
  );
}

type MetricTone = "neutral" | "positive" | "warning" | "negative" | "info" | "research";

export function MetricCard({
  label,
  value,
  detail,
  tone = "neutral",
  className,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: MetricTone;
  className?: string;
}) {
  return (
    <article className={cn("metric-card", `metric-card-${tone}`, className)}>
      <span>{label}</span>
      <b>{value}</b>
      {detail && <small>{detail}</small>}
    </article>
  );
}

/** A compact terminal surface used for data-first regions of the overview. */
export function TerminalPanel({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn("terminal-panel", className)} {...props}>
      {children}
    </section>
  );
}

/** Keeps labels visually subordinate to financial values everywhere it is used. */
export function MetricValue({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: MetricTone;
}) {
  return (
    <div className={cn("metric-value", `metric-value-${tone}`)}>
      <span>{label}</span>
      <b>{value}</b>
      {detail && <small>{detail}</small>}
    </div>
  );
}

/** Semantic status card for a single model or feed in the research terminal. */
export function StatusCard({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail: ReactNode;
  tone?: MetricTone;
}) {
  return (
    <article className={cn("status-card", `status-card-${tone}`)}>
      <span>{label}</span>
      <b>{value}</b>
      <small>{detail}</small>
    </article>
  );
}

export function StatusBadge({
  children,
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: MetricTone }) {
  return (
    <span
      className={cn("status-badge", `status-badge-${tone}`, className)}
      {...props}
    >
      {children}
    </span>
  );
}
