
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
import { queryClient } from "./lib/queryClient";
import { initializeSecurity } from "./lib/security";

if (import.meta.env?.VITE_DRY_RUN === "1") {
  console.info("DRY_RUN=1 — Command Center is running in read-only mode.");
  document.documentElement.dataset.dryRun = "true";
}

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
