import { useEffect, useRef, useState } from 'react';

export function usePolling<T>(fn: () => Promise<T>, ms: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await fn();
        if (!cancelled) setData(result);
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

    tick();

    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [fn, ms, enabled]);

  return { data, error };
}
