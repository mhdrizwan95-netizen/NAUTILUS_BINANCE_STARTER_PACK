
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import { AppErrorBoundary } from "./components/ErrorBoundary";
import { QueryProvider } from "./components/QueryProvider";
import {
  setupGlobalErrorHandling,
  setupPerformanceObserver,
  setupQueryMonitoring,
  trackWebVitals
} from "./lib/monitoring";
import { initializeSecurity } from "./lib/security";
import { queryClient } from "./lib/queryClient";

// Initialize monitoring and security
setupGlobalErrorHandling();
setupPerformanceObserver();
setupQueryMonitoring(queryClient);
trackWebVitals();
initializeSecurity();

createRoot(document.getElementById("root")!).render(
  <AppErrorBoundary>
    <QueryProvider>
      <App />
    </QueryProvider>
  </AppErrorBoundary>
);
