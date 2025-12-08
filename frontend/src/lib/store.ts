import { useMemo } from "react";
import { create, type StoreApi } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

import type { PageMetadata } from "./api";
import { createDefaultDashboardFilters, type DashboardFiltersState } from "./dashboardFilters";
import type { ModeType, GlobalMetrics, Venue, StrategyPerformance } from "../types/trading";

type NautilusWindow = Window & { __NAUTILUS_DISABLE_PERSIST__?: boolean };

// App-wide state interface
interface AppState {
  // Trading mode
  mode: ModeType;
  // User preferences
  preferences: {
    theme: "light" | "dark" | "system";
    autoRefresh: boolean;
    refreshInterval: number; // in seconds
    soundEnabled: boolean;
    notificationsEnabled: boolean;
  };
  // Ops auth context (memory only)
  opsAuth: {
    token: string;
    actor: string;
  };
  // Real-time data
  realTimeData: {
    globalMetrics: GlobalMetrics | null;
    performances: StrategyPerformance[];
    venues: Venue[];
    lastUpdate: number | null;
  };
  // UI state
  ui: {
    sidebarOpen: boolean;
    activeTab: string;
    loadingStates: Record<string, boolean>;
    dashboardFilters: DashboardFiltersState;
    pagination: Record<string, PageMetadata | null>;
  };
}

// Actions interface
export interface AppActions {
  // Mode actions
  setMode: (mode: ModeType) => void;

  // Preferences actions
  updatePreferences: (preferences: Partial<AppState["preferences"]>) => void;
  resetPreferences: () => void;

  // Ops auth actions
  setOpsToken: (token: string) => void;
  setOpsActor: (actor: string) => void;
  clearOpsAuth: () => void;

  // Real-time data actions
  updateGlobalMetrics: (metrics: GlobalMetrics) => void;
  updatePerformances: (performances: StrategyPerformance[]) => void;
  updateVenues: (venues: Venue[]) => void;
  updateRealTimeData: (data: Partial<AppState["realTimeData"]>) => void;

  // UI actions
  setSidebarOpen: (open: boolean) => void;
  setActiveTab: (tab: string) => void;
  setLoadingState: (key: string, loading: boolean) => void;
  clearLoadingStates: () => void;
  setDashboardFilters: (filters: DashboardFiltersState) => void;
  setPagination: (key: string, page: PageMetadata | null) => void;
  clearPagination: (...keys: string[]) => void;

  // Utility actions
  reset: () => void;
}

// Default state
const defaultState: AppState = {
  mode: "paper",
  preferences: {
    theme: "dark",
    autoRefresh: true,
    refreshInterval: 30,
    soundEnabled: true,
    notificationsEnabled: true,
  },
  opsAuth: {
    token: "dev-token",
    actor: "dev-user",
  },
  realTimeData: {
    globalMetrics: null,
    performances: [],
    venues: [],
    lastUpdate: null,
  },
  ui: {
    sidebarOpen: true,
    activeTab: "dashboard",
    loadingStates: {},
    dashboardFilters: createDefaultDashboardFilters(),
    pagination: {},
  },
};

const isSamePage = (a: PageMetadata | null, b: PageMetadata | null): boolean => {
  if (!a && !b) return true;
  if (!a || !b) return false;
  return (
    a.nextCursor === b.nextCursor &&
    a.prevCursor === b.prevCursor &&
    a.limit === b.limit &&
    (a.totalHint ?? null) === (b.totalHint ?? null) &&
    (a.hasMore ?? false) === (b.hasMore ?? false)
  );
};

type StoreCreator = (
  set: (
    nextState: AppState | Partial<AppState> | ((state: AppState) => AppState | Partial<AppState>),
  ) => void,
  _get: () => AppState,
  _store: StoreApi<AppState>,
) => AppState & AppActions;

// Helper creator shared by persisted and ephemeral stores
const createAppStore: StoreCreator = (set, _get, _store) => {
  void _get;
  void _store;
  type SetterArg = Parameters<typeof set>[0];
  const apply = (label: string, updater: SetterArg) => {
    if (typeof window !== "undefined" && import.meta.env.DEV) {
      const win = window as NautilusWindow & {
        __NAUTILUS_STORE_COUNTS?: Record<string, number>;
        __NAUTILUS_LAST_ACTION?: string;
      };
      const counts = (win.__NAUTILUS_STORE_COUNTS ??= {});
      counts[label] = (counts[label] ?? 0) + 1;
      win.__NAUTILUS_LAST_ACTION = label;
      if (counts[label] <= 5 || counts[label] % 25 === 0) {
        // eslint-disable-next-line no-console
        console.log(`[store:${label}]`, counts[label]);
      }
    }
    set(updater);
  };
  return {
    ...defaultState,

    // Mode actions
    setMode: (mode) => apply("setMode", { mode }),

    // Preferences actions
    updatePreferences: (preferences) =>
      apply("updatePreferences", (state) => ({
        preferences: { ...state.preferences, ...preferences },
      })),
    resetPreferences: () =>
      apply("resetPreferences", () => ({
        preferences: defaultState.preferences,
      })),

    // Ops auth actions
    setOpsToken: (token) =>
      apply("setOpsToken", (state) => ({
        opsAuth: { ...state.opsAuth, token },
      })),
    setOpsActor: (actor) =>
      apply("setOpsActor", (state) => ({
        opsAuth: { ...state.opsAuth, actor },
      })),
    clearOpsAuth: () =>
      apply("clearOpsAuth", () => ({
        opsAuth: defaultState.opsAuth,
      })),

    // Real-time data actions
    updateGlobalMetrics: (metrics) =>
      apply("updateGlobalMetrics", (state) => ({
        realTimeData: {
          ...state.realTimeData,
          globalMetrics: metrics,
          lastUpdate: Date.now(),
        },
      })),
    updatePerformances: (performances) =>
      apply("updatePerformances", (state) => ({
        realTimeData: {
          ...state.realTimeData,
          performances,
          lastUpdate: Date.now(),
        },
      })),
    updateVenues: (venues) =>
      apply("updateVenues", (state) => ({
        realTimeData: {
          ...state.realTimeData,
          venues,
          lastUpdate: Date.now(),
        },
      })),
    updateRealTimeData: (data) =>
      apply("updateRealTimeData", (state) => ({
        realTimeData: {
          ...state.realTimeData,
          ...data,
          lastUpdate: Date.now(),
        },
      })),

    // UI actions
    setSidebarOpen: (sidebarOpen) =>
      apply("setSidebarOpen", (state) => ({
        ui: { ...state.ui, sidebarOpen },
      })),
    setActiveTab: (activeTab) =>
      apply("setActiveTab", (state) => ({
        ui: { ...state.ui, activeTab },
      })),
    setLoadingState: (key, loading) =>
      apply("setLoadingState", (state) => ({
        ui: {
          ...state.ui,
          loadingStates: {
            ...state.ui.loadingStates,
            [key]: loading,
          },
        },
      })),
    clearLoadingStates: () =>
      apply("clearLoadingStates", (state) => ({
        ui: { ...state.ui, loadingStates: {} },
      })),
    setDashboardFilters: (filters) =>
      apply("setDashboardFilters", (state) => ({
        ui: { ...state.ui, dashboardFilters: filters },
      })),
    setPagination: (key, page) =>
      apply("setPagination", (state) => {
        const current = state.ui.pagination[key] ?? null;
        const nextValue = page ?? null;
        if (isSamePage(current, nextValue)) {
          return state;
        }
        const nextPagination = { ...state.ui.pagination };
        if (nextValue === null) {
          delete nextPagination[key];
        } else {
          nextPagination[key] = nextValue;
        }
        return {
          ui: { ...state.ui, pagination: nextPagination },
        };
      }),
    clearPagination: (...keys) =>
      apply("clearPagination", (state) => {
        if (!keys.length) {
          if (Object.keys(state.ui.pagination).length === 0) {
            return state;
          }
          return {
            ui: { ...state.ui, pagination: {} },
          };
        }

        let changed = false;
        const nextPagination = { ...state.ui.pagination };
        keys.forEach((key) => {
          if (key in nextPagination) {
            delete nextPagination[key];
            changed = true;
          }
        });

        if (!changed) {
          return state;
        }

        return {
          ui: { ...state.ui, pagination: nextPagination },
        };
      }),

    // Utility actions
    reset: () => apply("reset", defaultState),
  };
};

const shouldPersist = () =>
  typeof window !== "undefined" && !(window as NautilusWindow).__NAUTILUS_DISABLE_PERSIST__;

const storeInitializer = shouldPersist()
  ? persist(createAppStore, {
    name: "nautilus-app-store",
    storage: createJSONStorage(() => localStorage),
    // Only persist preferences and UI state, not real-time data
    partialize: (state) => ({
      preferences: state.preferences,
      ui: {
        sidebarOpen: state.ui.sidebarOpen,
        activeTab: state.ui.activeTab,
        dashboardFilters: state.ui.dashboardFilters,
        pagination: state.ui.pagination,
      },
    }),
  })
  : createAppStore;

if (!shouldPersist()) {
  console.warn("App store persistence disabled");
}

export const useAppStore = create<AppState & AppActions>()(storeInitializer);

// Selectors for commonly used state slices
export const useMode = () => useAppStore((state) => state.mode);
export const usePreferences = () => useAppStore((state) => state.preferences);
export const useRealTimeData = () => useAppStore((state) => state.realTimeData);
export const useUIState = () => useAppStore((state) => state.ui);

// Action selectors
export const useModeActions = () => {
  const setMode = useAppStore((state) => state.setMode);
  return useMemo(() => ({ setMode }), [setMode]);
};
export const usePreferenceActions = () => {
  const updatePreferences = useAppStore((state) => state.updatePreferences);
  const resetPreferences = useAppStore((state) => state.resetPreferences);
  return useMemo(
    () => ({
      updatePreferences,
      resetPreferences,
    }),
    [updatePreferences, resetPreferences],
  );
};
export const useRealTimeActions = (): Pick<
  AppActions,
  "updateGlobalMetrics" | "updatePerformances" | "updateVenues" | "updateRealTimeData"
> => {
  const updateGlobalMetrics = useAppStore((state) => state.updateGlobalMetrics);
  const updatePerformances = useAppStore((state) => state.updatePerformances);
  const updateVenues = useAppStore((state) => state.updateVenues);
  const updateRealTimeData = useAppStore((state) => state.updateRealTimeData);
  return useMemo(
    () => ({
      updateGlobalMetrics,
      updatePerformances,
      updateVenues,
      updateRealTimeData,
    }),
    [updateGlobalMetrics, updatePerformances, updateVenues, updateRealTimeData],
  );
};
export const useUIActions = () => {
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setActiveTab = useAppStore((state) => state.setActiveTab);
  const setLoadingState = useAppStore((state) => state.setLoadingState);
  const clearLoadingStates = useAppStore((state) => state.clearLoadingStates);
  const setDashboardFilters = useAppStore((state) => state.setDashboardFilters);
  return useMemo(
    () => ({
      setSidebarOpen,
      setActiveTab,
      setLoadingState,
      clearLoadingStates,
      setDashboardFilters,
    }),
    [setSidebarOpen, setActiveTab, setLoadingState, clearLoadingStates, setDashboardFilters],
  );
};

export const useDashboardFilters = (): DashboardFiltersState =>
  useAppStore((state) => state.ui.dashboardFilters);

export const useDashboardFilterActions = (): Pick<AppActions, "setDashboardFilters"> => {
  const setDashboardFilters = useAppStore((state) => state.setDashboardFilters);
  return useMemo(() => ({ setDashboardFilters }), [setDashboardFilters]);
};

export const usePagination = (key: string) =>
  useAppStore((state) => state.ui.pagination[key] ?? null);

export const usePaginationActions = (): Pick<AppActions, "setPagination" | "clearPagination"> => {
  const setPagination = useAppStore((state) => state.setPagination);
  const clearPagination = useAppStore((state) => state.clearPagination);
  return useMemo(
    () => ({
      setPagination,
      clearPagination,
    }),
    [setPagination, clearPagination],
  );
};
