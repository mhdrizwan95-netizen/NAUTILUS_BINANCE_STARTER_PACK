import { useEffect, useRef, useState } from "react";

import { stableHash } from "./equality";

export function usePolling<T>(
  fn: () => Promise<T>,
  ms: number,
  enabled = true,
  isEqual: (previous: T | null, next: T) => boolean = Object.is,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const timer = useRef<number | null>(null);
  const lastData = useRef<T | null>(null);
  const lastHash = useRef<string | null>(null);
  const fnRef = useRef(fn);
  const comparatorRef = useRef(isEqual);
  const liveDisabled = (import.meta.env?.VITE_LIVE_OFF ?? "false") === "true";
  const pollingEnabled = enabled && !liveDisabled;

  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);

  useEffect(() => {
    comparatorRef.current = isEqual;
  }, [isEqual]);

  useEffect(() => {
    if (!pollingEnabled) return undefined;
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await fnRef.current();
        if (cancelled) {
          return;
        }
        const nextHash = stableHash(result);
        if (comparatorRef.current(lastData.current, result) || lastHash.current === nextHash) {
          lastHash.current = nextHash;
          lastData.current = result;
          return;
        }
        lastHash.current = nextHash;
        lastData.current = result;
        setData(result);
      } catch (err) {
        if (!cancelled && err instanceof Error) {
          setError(err);
        }
      } finally {
        if (!cancelled) {
          timer.current = window.setTimeout(tick, ms);
        }
      }
    };

    void tick();

    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
      lastData.current = null;
      lastHash.current = null;
    };
  }, [ms, pollingEnabled]);

  return { data, error };
}
