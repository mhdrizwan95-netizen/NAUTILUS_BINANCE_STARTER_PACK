import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { App } from "./App";
import type * as ApiModule from "./lib/api";
import { queryClient } from "./lib/queryClient";

vi.mock("./components/TopHUD", () => ({
  TopHUD: () => <div data-testid="top-hud">TopHUD</div>,
}));

vi.mock("./components/TabbedInterface", () => ({
  TabbedInterface: () => <div data-testid="tabbed-interface">Tabs</div>,
}));

const mockSummary = vi.hoisted(() => vi.fn());
const mockHealth = vi.hoisted(() => vi.fn());
const mockConfig = vi.hoisted(() => vi.fn());
const mockOpsStatus = vi.hoisted(() => vi.fn());

vi.mock("./lib/api", async () => {
  const actual = await vi.importActual<typeof ApiModule>("./lib/api");
  return {
    ...actual,
    getDashboardSummary: mockSummary,
    getHealth: mockHealth,
    getConfigEffective: mockConfig,
    getOpsStatus: mockOpsStatus,
  };
});

const renderApp = () =>
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );

describe("App boot flow", () => {
  beforeEach(() => {
    queryClient.clear();
    mockSummary.mockImplementation(() =>
      Promise.resolve({
        kpis: {
          totalPnl: 0,
          winRate: 0,
          sharpe: 0,
          maxDrawdown: 0,
          openPositions: 0,
        },
        equityByStrategy: [],
        pnlBySymbol: [],
        returns: [],
      }),
    );
    mockHealth.mockImplementation(() =>
      Promise.resolve({
        venues: [
          { name: "Binance Spot", status: "ok", latencyMs: 50, queue: 1 },
          { name: "Binance Futures", status: "ok", latencyMs: 70, queue: 2 },
        ],
      }),
    );
    mockConfig.mockImplementation(() =>
      Promise.resolve({
        effective: { DRY_RUN: true },
        overrides: {},
      }),
    );
    mockOpsStatus.mockImplementation(() =>
      Promise.resolve({ ok: true, state: { trading_enabled: true } }),
    );
  });

  it("exits boot once dashboard and health data resolve", async () => {
    await act(async () => {
      renderApp();
    });

    expect(await screen.findByTestId("top-hud", undefined, { timeout: 5_000 })).toBeInTheDocument();
  });

  it("falls back to degraded mode when a critical API fails", async () => {
    mockSummary.mockImplementationOnce(() => Promise.reject(new Error("boom")));

    await act(async () => {
      renderApp();
    });

    await waitFor(
      () => expect(screen.queryByText(/INITIALIZING NEURAL NETWORK/i)).not.toBeInTheDocument(),
      { timeout: 5_000 },
    );
  });
});
