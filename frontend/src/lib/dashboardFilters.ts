import type { DateRange } from 'react-day-picker';

export type DashboardFiltersState = {
  from: string | null;
  to: string | null;
  strategies: string[];
  symbols: string[];
};

const daysAgo = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date;
};

export const createDefaultDashboardFilters = (): DashboardFiltersState => {
  const to = new Date();
  const from = daysAgo(7);

  return {
    from: from.toISOString(),
    to: to.toISOString(),
    strategies: [],
    symbols: [],
  };
};

export const buildSummarySearchParams = (filters: DashboardFiltersState): URLSearchParams => {
  const params = new URLSearchParams();

  if (filters.from) {
    params.set('from', filters.from);
  }

  if (filters.to) {
    params.set('to', filters.to);
  }

  filters.strategies.forEach((strategyId) => params.append('strategies[]', strategyId));
  filters.symbols.forEach((symbol) => params.append('symbols[]', symbol));

  return params;
};

export const toDateRange = (filters: DashboardFiltersState): DateRange | undefined => {
  if (!filters.from && !filters.to) {
    return undefined;
  }

  return {
    from: filters.from ? new Date(filters.from) : undefined,
    to: filters.to ? new Date(filters.to) : undefined,
  };
};

export const fromDateRange = (range: DateRange | undefined) => {
  const normalized = {
    from: range?.from ? range.from.toISOString() : null,
    to: range?.to ? range.to.toISOString() : null,
  };

  // If range has a start but no end, default end to start
  if (normalized.from && !normalized.to) {
    normalized.to = normalized.from;
  }

  return normalized;
};
