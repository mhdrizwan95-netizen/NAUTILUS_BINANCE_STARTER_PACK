import { useEffect, useRef, useState } from 'react';

export function usePolling<T>(
  fn: () => Promise<T>,
  ms: number,
  enabled = true,
  isEqual: (previous: T | null, next: T) => boolean = Object.is
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const timer = useRef<number | null>(null);
  const lastData = useRef<T | null>(null);
  const fnRef = useRef(fn);
  const comparatorRef = useRef(isEqual);
  const liveDisabled = (import.meta as any)?.env?.VITE_LIVE_OFF === 'true';
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
        if (!cancelled && !comparatorRef.current(lastData.current, result)) {
          lastData.current = result;
          setData(result);
        }
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
      lastData.current = null;
    };
  }, [ms, pollingEnabled]);

  return { data, error };
}
