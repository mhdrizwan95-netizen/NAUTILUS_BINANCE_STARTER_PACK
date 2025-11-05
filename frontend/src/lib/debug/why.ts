import { useEffect, useRef } from 'react';

type PropsRecord = Record<string, unknown>;

export function useWhyDidYouUpdate(componentName: string, props: PropsRecord): void {
  if (!import.meta.env.DEV) {
    return;
  }
  const previousProps = useRef<PropsRecord | null>(null);

  useEffect(() => {
    if (previousProps.current) {
      const changes: Record<string, { from: unknown; to: unknown }> = {};
      const allKeys = new Set([
        ...Object.keys(previousProps.current),
        ...Object.keys(props),
      ]);
      allKeys.forEach((key) => {
        const previousValue = previousProps.current?.[key];
        const nextValue = props[key];
        if (!Object.is(previousValue, nextValue)) {
          changes[key] = {
            from: previousValue,
            to: nextValue,
          };
        }
      });
      if (Object.keys(changes).length > 0) {
        // eslint-disable-next-line no-console
        console.debug(`[why-did-you-update] ${componentName}`, changes);
      }
    }
    previousProps.current = props;
  });
}

export function useRenderCounter(componentName: string): void {
  if (!import.meta.env.DEV) {
    return;
  }
  const renders = useRef(0);
  renders.current += 1;
  // eslint-disable-next-line no-console
  console.debug(`[render-count] ${componentName} render #${renders.current}`);
}
