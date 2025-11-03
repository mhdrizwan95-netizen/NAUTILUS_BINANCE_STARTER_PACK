import React from 'react';
import { ErrorBoundary as ReactErrorBoundary } from 'react-error-boundary';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from './ui/button';
import { Card } from './ui/card';

interface ErrorFallbackProps {
  error: Error;
  resetErrorBoundary: () => void;
}

function ErrorFallback({ error, resetErrorBoundary }: ErrorFallbackProps) {
  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="max-w-md w-full p-6 text-center">
        <div className="flex justify-center mb-4">
          <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
            <AlertTriangle className="w-6 h-6 text-red-400" />
          </div>
        </div>
        <h2 className="text-lg font-semibold text-zinc-100 mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-zinc-400 mb-6">
          An unexpected error occurred. Please try refreshing the page.
        </p>
        <div className="space-y-3">
          <Button onClick={resetErrorBoundary} className="w-full">
            <RefreshCw className="w-4 h-4 mr-2" />
            Try Again
          </Button>
          <Button
            variant="outline"
            onClick={() => window.location.reload()}
            className="w-full"
          >
            Reload Page
          </Button>
        </div>
        {process.env.NODE_ENV === 'development' && (
          <details className="mt-4 text-left">
            <summary className="text-xs text-zinc-500 cursor-pointer">
              Error Details (Development)
            </summary>
            <pre className="mt-2 text-xs text-red-400 bg-zinc-900 p-2 rounded overflow-auto">
              {error.message}
              {error.stack && `\n\n${error.stack}`}
            </pre>
          </details>
        )}
      </Card>
    </div>
  );
}

interface AppErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ComponentType<ErrorFallbackProps>;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

export function AppErrorBoundary({
  children,
  fallback: Fallback = ErrorFallback,
  onError
}: AppErrorBoundaryProps) {
  const handleError = (error: Error, errorInfo: React.ErrorInfo) => {
    console.error('AppErrorBoundary captured error:', error, errorInfo);
    // Log to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('Error Boundary caught an error:', error, errorInfo);
    }

    // Call custom error handler if provided
    onError?.(error, errorInfo);

    // TODO: Send to error tracking service (Sentry, etc.)
    // logErrorToService(error, errorInfo);
  };

  return (
    <ReactErrorBoundary
      FallbackComponent={Fallback}
      onError={handleError}
      onReset={() => {
        // Clear any cached error state
        window.location.reload();
      }}
    >
      {children}
    </ReactErrorBoundary>
  );
}

// Component-level error boundary for isolated failures
export function ComponentErrorBoundary({
  children,
  fallback: Fallback,
  onError
}: {
  children: React.ReactNode;
  fallback?: React.ComponentType<ErrorFallbackProps>;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}) {
  return (
    <ReactErrorBoundary
      FallbackComponent={Fallback || ErrorFallback}
      onError={onError}
      onReset={() => {
        // Component-specific reset logic can be added here
      }}
    >
      {children}
    </ReactErrorBoundary>
  );
}
