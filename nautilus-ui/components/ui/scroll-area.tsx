import clsx from "clsx";
import type { HTMLAttributes } from "react";

export function ScrollArea({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx("relative overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-700/60", className)}
      {...props}
    />
  );
}
