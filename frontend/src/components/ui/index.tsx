// Shared UI building blocks: buttons, badges, modal, drawer, toggle and friends.

import { Dialog, DialogPanel, DialogTitle, Switch } from "@headlessui/react";
import { Check, Copy, Loader2, X } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { twMerge } from "tailwind-merge";

/** Join class names; later Tailwind classes override earlier conflicting ones. */
export function cx(...parts: (string | false | null | undefined)[]) {
  return twMerge(parts.filter(Boolean).join(" "));
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:brightness-110 shadow-sm",
  secondary: "bg-card text-ink border border-line hover:border-line-strong hover:bg-sunken",
  ghost: "text-ink-2 hover:bg-sunken hover:text-ink",
  danger: "bg-danger text-white hover:brightness-110",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "icon"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition select-none",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : size === "icon" ? "size-9 shrink-0 p-0" : "h-10 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function IconButton({ label, className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex size-8 items-center justify-center rounded-lg text-muted transition hover:bg-sunken hover:text-ink disabled:opacity-40",
        className,
      )}
    >
      {children}
    </button>
  );
}

type Tone = "neutral" | "accent" | "warn" | "danger" | "info";
const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2 border-line",
  accent: "bg-accent-soft text-accent border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  info: "bg-sunken text-load border-line",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[11px] leading-none whitespace-nowrap", TONES[tone], className)}
    >
      {children}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin", className)} aria-label="Loading" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-md", className)} aria-hidden />;
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = "max-w-md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: string;
}) {
  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-[2px]" aria-hidden />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className={cx("w-full rounded-2xl border border-line bg-panel p-5 shadow-2xl", width)}>
          <div className="mb-4 flex items-start justify-between gap-4">
            <DialogTitle className="font-display text-lg font-semibold">{title}</DialogTitle>
            <IconButton label="Close" onClick={onClose}>
              <X className="size-4" />
            </IconButton>
          </div>
          {children}
        </DialogPanel>
      </div>
    </Dialog>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  side = "right",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  side?: "right" | "left";
}) {
  return (
    <Dialog open={open} onClose={onClose} className="relative z-40">
      <div className="fixed inset-0 bg-black/30" aria-hidden />
      <div className={cx("fixed inset-y-0 flex w-full max-w-md", side === "right" ? "right-0" : "left-0")}>
        <DialogPanel className="flex w-full flex-col border-line bg-panel shadow-2xl sm:border-l">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <DialogTitle className="font-display text-lg font-semibold">{title}</DialogTitle>
            <IconButton label="Close" onClick={onClose}>
              <X className="size-4" />
            </IconButton>
          </div>
          <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="border-t border-line px-5 py-4">{footer}</div>}
        </DialogPanel>
      </div>
    </Dialog>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <Switch
      checked={checked}
      onChange={onChange}
      aria-label={label}
      className={cx(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border transition",
        checked ? "border-accent bg-accent" : "border-line-strong bg-sunken",
      )}
    >
      <span
        className={cx(
          "pointer-events-none mt-[2px] inline-block size-[18px] rounded-full bg-white shadow transition",
          checked ? "translate-x-[22px]" : "translate-x-[2px]",
        )}
      />
    </Switch>
  );
}

export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted transition hover:bg-sunken hover:text-ink", className)}
      aria-label={copied ? "Copied" : label}
    >
      {copied ? <Check className="size-3.5 text-accent" /> : <Copy className="size-3.5" />}
      <span>{copied ? "Copied" : label}</span>
    </button>
  );
}

export function ErrorNote({ message, hint, className }: { message: string; hint?: string | null; className?: string }) {
  return (
    <div role="alert" className={cx("rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger", className)}>
      <div className="font-medium">{message}</div>
      {hint && <div className="mt-0.5 text-ink-2">{hint}</div>}
    </div>
  );
}

/** A thin horizontal meter (0..1). */
export function Meter({ value, className, colorClass = "bg-accent" }: { value: number; className?: string; colorClass?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={cx("h-1.5 overflow-hidden rounded-full bg-sunken", className)} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <div className={cx("h-full rounded-full transition-[width] duration-300", colorClass)} style={{ width: `${pct}%` }} />
    </div>
  );
}
