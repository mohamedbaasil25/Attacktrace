import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";

const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-surface-0 hover:brightness-110",
  secondary: "border border-line-2 text-ink-1 bg-surface-2 hover:bg-surface-3",
  ghost: "text-ink-2 hover:text-ink-1 hover:bg-surface-2",
};

const BASE =
  "inline-flex min-h-[32px] items-center justify-center gap-2 rounded-md px-3 text-label font-medium transition-colors duration-fast ease-out disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function Spinner() {
  return <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  icon?: ReactNode;
}

/** Tokenized button primitive: the only place variant styling is decided. Every clickable action
 *  in the app (Launch, Reset, Isolate, tab buttons) should use this instead of ad-hoc classes. */
export function Button({
  variant = "secondary",
  loading = false,
  icon,
  disabled,
  className = "",
  children,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`${BASE} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

interface LinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: Variant;
  icon?: ReactNode;
}

/** Same styling as `Button`, but a real `<a>` -- for a download/navigation action. A `<button>`
 *  nested inside an `<a>` (the previous shape of the Report download link) is invalid HTML and
 *  leaves the inner button with no accessible name (axe `button-name`, critical). */
export function LinkButton({ variant = "secondary", icon, className = "", children, ...rest }: LinkProps) {
  return (
    <a className={`${BASE} ${VARIANT[variant]} ${className}`} {...rest}>
      {icon}
      {children}
    </a>
  );
}
