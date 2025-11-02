import { create } from 'zustand';
import { shallow } from 'zustand/shallow';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ModeType, GlobalMetrics, Venue, StrategyPerformance } from '../types/trading';
import {
  createDefaultDashboardFilters,
  type DashboardFiltersState,
} from './dashboardFilters';

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
  };
}

// Actions interface
interface AppActions {
  // Mode actions
  setMode: (mode: ModeType) => void;

  // Preferences actions
  updatePreferences: (preferences: Partial<AppState['preferences']>) => void;
  resetPreferences: () => void;

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
  },
};

type StoreCreator = (
  set: (nextState: AppState | Partial<AppState> | ((state: AppState) => AppState | Partial<AppState>)) => void,
  get: () => AppState,
  store: any
) => AppState & AppActions;

// Helper creator shared by persisted and ephemeral stores
const createAppStore: StoreCreator = (set, get) => ({
      ...defaultState,

      // Mode actions
      setMode: (mode) => set({ mode }),

      // Preferences actions
      updatePreferences: (preferences) =>
        set((state) => ({
          preferences: { ...state.preferences, ...preferences },
        })),
      resetPreferences: () =>
        set((state) => ({
          preferences: defaultState.preferences,
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

      // Utility actions
      reset: () => set(defaultState),
});

const shouldPersist = () =>
  typeof window !== 'undefined' && !(window as any).__NAUTILUS_DISABLE_PERSIST__;

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
