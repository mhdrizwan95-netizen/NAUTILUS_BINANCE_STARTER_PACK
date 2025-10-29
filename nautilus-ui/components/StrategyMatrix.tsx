"use client";

import { Fragment } from "react";
import { StrategyPod } from "@/components/StrategyPod";
import type { StrategyPerformance, Strategy, Venue } from "@/lib/types";

interface StrategyMatrixProps {
  performances: StrategyPerformance[];
  strategies: Strategy[];
  venues: Venue[];
  onSelect: (performance: StrategyPerformance, strategy: Strategy, venue: Venue) => void;
}

export function StrategyMatrix({ performances, strategies, venues, onSelect }: StrategyMatrixProps) {
  return (
    <div className="space-y-4 pr-2">
      {strategies.map((strategy) => (
        <Fragment key={strategy.id}>
          <section className="space-y-3">
            <h3 className="uppercase tracking-[0.2em] text-xs text-zinc-500">{strategy.name}</h3>
            <div className="flex flex-wrap gap-4">
              {venues.map((venue) => {
                const performance = performances.find(
                  (p) => p.strategyId === strategy.id && p.venueId === venue.id,
                );
                if (!performance) return null;
                return (
                  <StrategyPod
                    key={`${strategy.id}-${venue.id}`}
                    performance={performance}
                    strategy={strategy}
                    venue={venue}
                    onClick={() => onSelect(performance, strategy, venue)}
                  />
                );
              })}
            </div>
          </section>
        </Fragment>
      ))}
    </div>
  );
}
