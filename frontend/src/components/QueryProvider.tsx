import { useEffect, useState, type ComponentType, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  const [Devtools, setDevtools] = useState<ComponentType | null>(null);

  useEffect(() => {
    if (import.meta.env.DEV) {
      import('@tanstack/react-query-devtools')
        .then((mod) => setDevtools(() => mod.ReactQueryDevtools))
        .catch(() => {
          console.warn('React Query Devtools not available; continuing without it');
        });
    }
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {/* React Query DevTools - only in development */}
      {Devtools ? <Devtools initialIsOpen={false} /> : null}
    </QueryClientProvider>
  );
}
