import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { clsx } from "clsx";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

const styles: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:opacity-90 border-accent",
  secondary: "bg-surface text-ink border-border-subtle hover:bg-surface-muted",
  quiet: "bg-transparent text-accent border-transparent hover:bg-surface-muted",
  danger: "bg-destructive text-white border-destructive hover:opacity-90",
};

interface SharedProps {
  children: ReactNode;
  variant?: ButtonVariant;
  className?: string;
}

type Props = SharedProps & ButtonHTMLAttributes<HTMLButtonElement> & { href?: string };

export default function Button({ children, variant = "primary", className, href, ...props }: Props) {
  const classes = clsx(
    "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus disabled:cursor-not-allowed disabled:opacity-50",
    styles[variant], className,
  );
  if (href) return <Link className={classes} href={href}>{children}</Link>;
  return <button className={classes} {...props}>{children}</button>;
}
