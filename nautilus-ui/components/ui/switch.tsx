import * as React from "react";
import clsx from "clsx";

export interface SwitchProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ checked = false, onCheckedChange, className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        aria-pressed={checked}
        onClick={() => onCheckedChange?.(!checked)}
        className={clsx(
          "relative h-5 w-10 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/40",
          checked ? "bg-emerald-500/60" : "bg-zinc-700",
          className,
        )}
        {...props}
      >
        <span
          className={clsx(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </button>
    );
  },
);

Switch.displayName = "Switch";
