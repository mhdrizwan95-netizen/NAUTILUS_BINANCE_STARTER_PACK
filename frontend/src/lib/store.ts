import { create, type StoreApi } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { shallow } from 'zustand/shallow';

import type { PageMetadata } from './api';
import {
  createDefaultDashboardFilters,
  type DashboardFiltersState,
} from './dashboardFilters';
import type { ModeType, GlobalMetrics, Venue, StrategyPerformance } from '../types/trading';

type NautilusWindow = Window & { __NAUTILUS_DISABLE_PERSIST__?: boolean };

// App-wide state interface
interface AppState {
  // Trading mode
  mode: ModeType;
  // User preferences
  preferences: {
    theme: 'light' | 'dark' | 'system';
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
interface AppActions {
  // Mode actions
  setMode: (mode: ModeType) => void;

  // Preferences actions
  updatePreferences: (preferences: Partial<AppState['preferences']>) => void;
  resetPreferences: () => void;

  // Ops auth actions
  setOpsToken: (token: string) => void;
  setOpsActor: (actor: string) => void;
  clearOpsAuth: () => void;

  // Real-time data actions
  updateGlobalMetrics: (metrics: GlobalMetrics) => void;
  updatePerformances: (performances: StrategyPerformance[]) => void;
  updateVenues: (venues: Venue[]) => void;
  updateRealTimeData: (data: Partial<AppState['realTimeData']>) => void;

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
  mode: 'paper',
  preferences: {
    theme: 'dark',
    autoRefresh: true,
    refreshInterval: 30,
    soundEnabled: true,
    notificationsEnabled: true,
  },
  opsAuth: {
    token: '',
    actor: '',
  },
  realTimeData: {
    globalMetrics: null,
    performances: [],
    venues: [],
    lastUpdate: null,
  },
  ui: {
    sidebarOpen: true,
    activeTab: 'dashboard',
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
  set: (nextState: AppState | Partial<AppState> | ((state: AppState) => AppState | Partial<AppState>)) => void,
  _get: () => AppState,
  _store: StoreApi<AppState>
) => AppState & AppActions;

// Helper creator shared by persisted and ephemeral stores
const createAppStore: StoreCreator = (set, _get, _store) => {
  void _get;
  void _store;
  return {
      ...defaultState,

      // Mode actions
      setMode: (mode) => set({ mode }),

      // Preferences actions
      updatePreferences: (preferences) =>
        set((state) => ({
          preferences: { ...state.preferences, ...preferences },
        })),
      resetPreferences: () =>
        set(() => ({
          preferences: defaultState.preferences,
        })),

      // Ops auth actions
      setOpsToken: (token) =>
        set((state) => ({
          opsAuth: { ...state.opsAuth, token },
        })),
      setOpsActor: (actor) =>
        set((state) => ({
          opsAuth: { ...state.opsAuth, actor },
        })),
      clearOpsAuth: () =>
        set(() => ({
          opsAuth: defaultState.opsAuth,
        })),

      // Real-time data actions
      updateGlobalMetrics: (metrics) =>
        set((state) => ({
          realTimeData: {
            ...state.realTimeData,
            globalMetrics: metrics,
            lastUpdate: Date.now(),
          },
        })),
      updatePerformances: (performances) =>
        set((state) => ({
          realTimeData: {
            ...state.realTimeData,
            performances,
            lastUpdate: Date.now(),
          },
        })),
      updateVenues: (venues) =>
        set((state) => ({
          realTimeData: {
            ...state.realTimeData,
            venues,
            lastUpdate: Date.now(),
          },
        })),
      updateRealTimeData: (data) =>
        set((state) => ({
          realTimeData: {
            ...state.realTimeData,
            ...data,
            lastUpdate: Date.now(),
          },
        })),

      // UI actions
      setSidebarOpen: (sidebarOpen) =>
        set((state) => ({
          ui: { ...state.ui, sidebarOpen },
        })),
      setActiveTab: (activeTab) =>
        set((state) => ({
          ui: { ...state.ui, activeTab },
        })),
      setLoadingState: (key, loading) =>
        set((state) => ({
          ui: {
            ...state.ui,
            loadingStates: {
              ...state.ui.loadingStates,
              [key]: loading,
            },
          },
        })),
      clearLoadingStates: () =>
        set((state) => ({
          ui: { ...state.ui, loadingStates: {} },
        })),
      setDashboardFilters: (filters) =>
        set((state) => ({
          ui: { ...state.ui, dashboardFilters: filters },
        })),
      setPagination: (key, page) =>
        set((state) => {
          const current = state.ui.pagination[key] ?? null;
          const nextValue = page ?? null;
          if (isSamePage(current, nextValue)) {
            return {};
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
        set((state) => {
          if (!keys.length) {
            if (Object.keys(state.ui.pagination).length === 0) {
              return {};
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
            return {};
          }

          return {
            ui: { ...state.ui, pagination: nextPagination },
          };
        }),

      // Utility actions
      reset: () => set(defaultState),
  };
};

const shouldPersist = () =>
  typeof window !== 'undefined' &&
  !(window as NautilusWindow).__NAUTILUS_DISABLE_PERSIST__;

const storeInitializer = shouldPersist()
  ? persist(createAppStore, {
      name: 'nautilus-app-store',
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
  console.warn('App store persistence disabled');
}

export const useAppStore = create<AppState & AppActions>()(storeInitializer);

// Selectors for commonly used state slices
export const useMode = () => useAppStore((state) => state.mode);
export const usePreferences = () => useAppStore((state) => state.preferences);
export const useRealTimeData = () => useAppStore((state) => state.realTimeData, shallow);
export const useUIState = () => useAppStore((state) => state.ui);

// Action selectors
export const useModeActions = () =>
  useAppStore((state) => ({ setMode: state.setMode }), shallow);
export const usePreferenceActions = () =>
  useAppStore(
    (state) => ({
      updatePreferences: state.updatePreferences,
      resetPreferences: state.resetPreferences,
    }),
    shallow
  );
export const useRealTimeActions = () =>
  useAppStore(
    (state) => ({
      updateGlobalMetrics: state.updateGlobalMetrics,
      updatePerformances: state.updatePerformances,
      updateVenues: state.updateVenues,
      updateRealTimeData: state.updateRealTimeData,
    }),
    shallow
  );
export const useUIActions = () =>
  useAppStore(
    (state) => ({
      setSidebarOpen: state.setSidebarOpen,
      setActiveTab: state.setActiveTab,
      setLoadingState: state.setLoadingState,
      clearLoadingStates: state.clearLoadingStates,
      setDashboardFilters: state.setDashboardFilters,
    }),
    shallow
  );

export const useDashboardFilters = () =>
  useAppStore((state) => state.ui.dashboardFilters, shallow);

export const useDashboardFilterActions = () =>
  useAppStore((state) => ({ setDashboardFilters: state.setDashboardFilters }), shallow);

export const usePagination = (key: string) =>
  useAppStore((state) => state.ui.pagination[key] ?? null);

export const usePaginationActions = () =>
  useAppStore(
    (state) => ({
      setPagination: state.setPagination,
      clearPagination: state.clearPagination,
    }),
    shallow,
  );
