import { QueryClient } from '@tanstack/react-query';

// Performance monitoring utilities
export class PerformanceMonitor {
  private static instance: PerformanceMonitor;
  private metrics: Map<string, number[]> = new Map();

  static getInstance(): PerformanceMonitor {
    if (!PerformanceMonitor.instance) {
      PerformanceMonitor.instance = new PerformanceMonitor();
    }
    return PerformanceMonitor.instance;
  }

  // Track API response times
  trackApiCall(endpoint: string, duration: number): void {
    if (!this.metrics.has(endpoint)) {
      this.metrics.set(endpoint, []);
    }
    const calls = this.metrics.get(endpoint)!;
    calls.push(duration);

    // Keep only last 100 calls for memory efficiency
    if (calls.length > 100) {
      calls.shift();
    }

    // Log slow requests (> 1000ms)
    if (duration > 1000) {
      console.warn(`Slow API call: ${endpoint} took ${duration}ms`);
    }
  }

  // Get average response time for endpoint
  getAverageResponseTime(endpoint: string): number {
    const calls = this.metrics.get(endpoint);
    if (!calls || calls.length === 0) return 0;

    return calls.reduce((sum, time) => sum + time, 0) / calls.length;
  }

  // Track component render times
  trackRender(componentName: string, duration: number): void {
    // Only track slow renders (> 16ms = 60fps)
    if (duration > 16) {
      console.warn(`Slow render: ${componentName} took ${duration}ms`);
    }
  }

  // Track WebSocket connection health
  trackWebSocketEvent(event: 'connect' | 'disconnect' | 'error' | 'reconnect'): void {
    console.log(`WebSocket ${event} at ${new Date().toISOString()}`);
  }

  // Get performance report
  getReport(): Record<string, any> {
    const report: Record<string, any> = {};

    for (const [endpoint, calls] of this.metrics.entries()) {
      report[endpoint] = {
        averageResponseTime: this.getAverageResponseTime(endpoint),
        totalCalls: calls.length,
        minTime: Math.min(...calls),
        maxTime: Math.max(...calls),
      };
    }

    return report;
  }
}

// Error tracking and reporting
export class ErrorTracker {
  private static instance: ErrorTracker;
  private errors: Array<{
    message: string;
    stack?: string;
    timestamp: number;
    context: Record<string, any>;
  }> = [];

  static getInstance(): ErrorTracker {
    if (!ErrorTracker.instance) {
      ErrorTracker.instance = new ErrorTracker();
    }
    return ErrorTracker.instance;
  }

  // Track application errors
  trackError(error: Error, context: Record<string, any> = {}): void {
    const errorInfo = {
      message: error.message,
      stack: error.stack,
      timestamp: Date.now(),
      context,
    };

    this.errors.push(errorInfo);

    // Keep only last 50 errors
    if (this.errors.length > 50) {
      this.errors.shift();
    }

    // Log to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('Error tracked:', errorInfo);
    }

    // Send to error tracking service (Sentry, etc.)
    this.sendToService(errorInfo);
  }

  // Track React Error Boundary errors
  trackReactError(error: Error, errorInfo: React.ErrorInfo): void {
    this.trackError(error, {
      componentStack: errorInfo.componentStack,
      errorBoundary: true,
    });
  }

  // Track API errors
  trackApiError(endpoint: string, error: Error, statusCode?: number): void {
    this.trackError(error, {
      endpoint,
      statusCode,
      type: 'api',
    });
  }

  // Send error to external service
  private sendToService(errorInfo: any): void {
    // TODO: Integrate with Sentry, LogRocket, or similar
    // Example:
    // Sentry.captureException(error, { extra: errorInfo.context });

    // For now, just store locally
    try {
      const existingErrors = JSON.parse(localStorage.getItem('app-errors') || '[]');
      existingErrors.push(errorInfo);
      // Keep only last 20 errors in localStorage
      if (existingErrors.length > 20) {
        existingErrors.splice(0, existingErrors.length - 20);
      }
      localStorage.setItem('app-errors', JSON.stringify(existingErrors));
    } catch (e) {
      // Ignore localStorage errors
    }
  }

  // Get recent errors
  getRecentErrors(limit = 10): any[] {
    return this.errors.slice(-limit);
  }

  // Clear error history
  clearErrors(): void {
    this.errors = [];
    localStorage.removeItem('app-errors');
  }
}

// Web Vitals tracking (placeholder - install web-vitals package for full implementation)
export function trackWebVitals(): void {
  // Track Core Web Vitals using Performance API
  if ('PerformanceObserver' in window) {
    console.log('Web Vitals tracking initialized (basic implementation)');

    // Basic LCP tracking
    const lcpObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const lastEntry = entries[entries.length - 1];
      console.log('LCP:', lastEntry.startTime);
    });
    lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });

    // Basic FID tracking
    const fidObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        console.log('FID:', (entry as any).processingStart - entry.startTime);
      }
    });
    fidObserver.observe({ entryTypes: ['first-input'] });
  }
}

// Query monitoring integration
export function setupQueryMonitoring(queryClient: QueryClient): void {
  // Track query performance
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const startTime = Date.now();
    const [url] = args;

    try {
      const response = await originalFetch(...args);
      const duration = Date.now() - startTime;

      // Track API call performance
      PerformanceMonitor.getInstance().trackApiCall(url as string, duration);

      return response;
    } catch (error) {
      const duration = Date.now() - startTime;
      PerformanceMonitor.getInstance().trackApiCall(url as string, duration);

      throw error;
    }
  };

  // Track query cache hits/misses
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type === 'added') {
      console.log('Query added to cache:', event.query.queryKey);
    } else if (event.type === 'removed') {
      console.log('Query removed from cache:', event.query.queryKey);
    }
  });
}

// User interaction tracking
export class UserTracker {
  private static instance: UserTracker;
  private interactions: Array<{
    type: string;
    target: string;
    timestamp: number;
  }> = [];

  static getInstance(): UserTracker {
    if (!UserTracker.instance) {
      UserTracker.instance = new UserTracker();
    }
    return UserTracker.instance;
  }

  trackInteraction(type: string, target: string): void {
    const interaction = {
      type,
      target,
      timestamp: Date.now(),
    };

    this.interactions.push(interaction);

    // Keep only last 100 interactions
    if (this.interactions.length > 100) {
      this.interactions.shift();
    }
  }

  getRecentInteractions(limit = 20): any[] {
    return this.interactions.slice(-limit);
  }
}

// Global error handler
export function setupGlobalErrorHandling(): void {
  // Handle unhandled promise rejections
  window.addEventListener('unhandledrejection', (event) => {
    ErrorTracker.getInstance().trackError(
      new Error(`Unhandled promise rejection: ${event.reason}`),
      { type: 'unhandledrejection' }
    );
  });

  // Handle uncaught errors
  window.addEventListener('error', (event) => {
    ErrorTracker.getInstance().trackError(
      event.error || new Error(event.message),
      {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        type: 'uncaughterror',
      }
    );
  });

  // Handle React Error Boundaries
  window.addEventListener('reactError', (event) => {
    const { error, errorInfo } = (event as any).detail;
    ErrorTracker.getInstance().trackReactError(error, errorInfo);
  });
}

// Performance observer for long tasks
export function setupPerformanceObserver(): void {
  if ('PerformanceObserver' in window) {
    // Observe long tasks (> 50ms)
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.duration > 50) {
          console.warn('Long task detected:', {
            duration: entry.duration,
            startTime: entry.startTime,
          });
        }
      }
    });

    observer.observe({ entryTypes: ['longtask'] });

    // Observe layout shifts (CLS)
    const layoutObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if ((entry as any).value > 0.1) {
          console.warn('Layout shift detected:', {
            value: (entry as any).value,
            startTime: entry.startTime,
          });
        }
      }
    });

    layoutObserver.observe({ entryTypes: ['layout-shift'] });
  }
}
