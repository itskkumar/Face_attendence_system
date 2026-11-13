"use client";
import { motion, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import { Search, X } from "lucide-react";
import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { statusColor } from "@/lib/status";
import { CountUp } from "./count-up";

export function GlassCard({ className, children, delay = 0, ...rest }: HTMLMotionProps<"div"> & { delay?: number }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" }}
      className={cn("glass rounded-xl2 p-5", className)}
      {...rest}
    >
      {children as ReactNode}
    </motion.div>
  );
}

type BtnVariant = "primary" | "ghost" | "danger" | "subtle";
interface BtnProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onDrag" | "onDragStart" | "onDragEnd" | "onAnimationStart"> {
  variant?: BtnVariant; loading?: boolean;
}
const VARIANTS: Record<BtnVariant, string> = {
  primary: "bg-primary text-white shadow-glow hover:brightness-110",
  ghost: "border border-[var(--glass-border)] hover:bg-[var(--glass-strong)]",
  subtle: "bg-[var(--glass-strong)] hover:brightness-110",
  danger: "bg-danger text-white hover:brightness-110",
};
export const GlassButton = forwardRef<HTMLButtonElement, BtnProps>(function GlassButton(
  { variant = "primary", loading, className, children, disabled, type = "button", ...rest }, ref) {
  return (
    <motion.button
      ref={ref} type={type} disabled={disabled || loading}
      whileHover={disabled || loading ? undefined : { y: -1 }} whileTap={disabled || loading ? undefined : { scale: 0.97 }}
      className={cn("inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", VARIANTS[variant], className)}
      {...rest}
    >
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children as ReactNode}
    </motion.button>
  );
});

export function GlassStatCard({ label, value, icon, suffix, decimals = 0, hint, delay = 0 }: {
  label: string; value: number | null | undefined; icon?: ReactNode; suffix?: string; decimals?: number; hint?: string; delay?: number;
}) {
  return (
    <GlassCard delay={delay} className="flex items-start justify-between gap-3">
      <div>
        <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
        <p className="mt-1 text-3xl font-semibold tabular-nums">
          {value === null || value === undefined ? "-" : <CountUp value={value} decimals={decimals} />}
          {suffix && <span className="ml-1 text-base text-muted">{suffix}</span>}
        </p>
        {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
      </div>
      {icon && <div className="rounded-xl bg-primary/15 p-2.5 text-primary">{icon}</div>}
    </GlassCard>
  );
}

export function GlassChartCard({ title, subtitle, children, className, action }: {
  title: string; subtitle?: string; children: ReactNode; className?: string; action?: ReactNode;
}) {
  return (
    <GlassCard className={className}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div><h3 className="text-sm font-semibold">{title}</h3>{subtitle && <p className="text-xs text-muted">{subtitle}</p>}</div>
        {action}
      </div>
      <div className="h-64 w-full">{children}</div>
    </GlassCard>
  );
}

export function StatusBadge({ status, label, color, pulse }: { status?: string; label?: string; color?: string; pulse?: boolean }) {
  const c = color ?? statusColor(status ?? "");
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium"
      style={{ color: c, borderColor: `${c}55`, background: `${c}1f` }}>
      <span className={cn("h-1.5 w-1.5 rounded-full", pulse && "animate-livepulse")} style={{ background: c }} />
      {label ?? status}
    </span>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search", className, label = "Search" }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string; label?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
      <input aria-label={label} className="field pl-9 pr-8" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {value && (
        <button type="button" aria-label="Clear search" onClick={() => onChange("")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:text-fg">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  const id = useId();
  return (
    <div role="tablist" className="glass inline-flex rounded-xl p-1">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn("relative rounded-lg px-4 py-1.5 text-sm transition", value === t.id ? "text-white" : "text-muted hover:text-fg")}>
          {value === t.id && <motion.span layoutId={`tab-${id}`} className="absolute inset-0 rounded-lg bg-primary" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
          <span className="relative">{t.label}</span>
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="rounded-2xl bg-primary/10 p-3 text-primary">{icon}</div>}
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("relative overflow-hidden rounded-xl bg-[var(--glass-strong)]", className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/10 to-transparent" />
    </div>
  );
}

export const Field = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }>(function Field(
  { label, error, className, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={className}>
      <label htmlFor={fid} className="label">{label}</label>
      <input id={fid} ref={ref} className="field" aria-invalid={Boolean(error)} aria-describedby={error ? `${fid}-err` : undefined} {...rest} />
      {error && <p id={`${fid}-err`} role="alert" className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
});
