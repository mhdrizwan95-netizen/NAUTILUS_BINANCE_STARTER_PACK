import { shallowEqualRecords, areVenueArraysEqual } from './equality';

export type SummarySnapshot = {
  kpis: Record<string, number>;
  equityByStrategy?: unknown[];
  pnlBySymbol?: unknown[];
  returns?: unknown[];
  [key: string]: unknown;
};

export function mergeMetricsSnapshot(
  existing: SummarySnapshot | undefined,
  payload: Record<string, number>
): SummarySnapshot {
  if (!existing) {
    return {
      kpis: payload,
      equityByStrategy: [],
      pnlBySymbol: [],
      returns: [],
    };
  }
  const mergedKpis = {
    ...existing.kpis,
    ...payload,
  };
  if (shallowEqualRecords(existing.kpis, mergedKpis)) {
    return existing;
  }
  return {
    ...existing,
    kpis: mergedKpis,
  };
}

export function mergeVenuesSnapshot<T extends { venues: Array<Record<string, unknown>> } | undefined>(
  existing: T,
  venues: Array<Record<string, unknown>>
): T | { venues: Array<Record<string, unknown>> } {
  const previousVenues = (existing?.venues as Array<Record<string, unknown>>) ?? [];
  if (areVenueArraysEqual(previousVenues, venues)) {
    return existing ?? { venues };
  }
  if (existing) {
    return {
      ...existing,
      venues,
    };
  }
  return { venues };
}
