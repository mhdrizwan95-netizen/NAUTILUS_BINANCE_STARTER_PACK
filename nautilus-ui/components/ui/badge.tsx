import clsx from "clsx";
import type { HTMLAttributes } from "react";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "outline";
}

export function Badge({ variant = "default", className, ...props }: BadgeProps) {
  const base = "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium";
  const styles =
    variant === "outline"
      ? "border border-zinc-700/60 text-zinc-400"
      : "bg-zinc-800/80 text-zinc-300";

  return <span className={clsx(base, styles, className)} {...props} />;
}
