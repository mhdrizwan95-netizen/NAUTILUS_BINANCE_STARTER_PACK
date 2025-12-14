
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Scan, TrendingUp, Trophy } from "lucide-react";
import { getScannerState } from "../../lib/api";
import { GlassCard } from "../ui/GlassCard";
import { Button } from "../ui/button";
import { Skeleton } from "../ui/skeleton";
import { cn } from "../../lib/utils";

export function MarketScannerTab() {
    const { data, isLoading, refetch, isRefetching } = useQuery({
        queryKey: ["scannerState"],
        queryFn: ({ signal }) => getScannerState(signal),
        refetchInterval: 30000,
    });

    const activeSymbols = data?.selected || [];
    const scores = data?.scores || {};
    const lastSelected = data?.last_selected || {};

    // Sort scores for display table
    const rankedAll = Object.entries(scores)
        .map(([symbol, score]) => ({
            symbol,
            score,
            isSelected: activeSymbols.includes(symbol),
            lastSelected: lastSelected[symbol] || 0,
        }))
        .sort((a, b) => b.score - a.score);

    return (
        <div className="flex flex-col !gap-6 w-full p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold text-zinc-100 flex items-center gap-2">
                        <Scan className="w-6 h-6 text-cyan-400" />
                        Market Scanner
                    </h2>
                    <p className="text-sm text-zinc-400">
                        Real-time universe selection based on Volume, Trend, and Volatility.
                    </p>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetch()}
                    disabled={isLoading || isRefetching}
                    className="gap-2"
                >
                    <RefreshCw className={cn("w-4 h-4", isRefetching && "animate-spin")} />
                    Refresh
                </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Active Universe Card */}
                <GlassCard className="md:col-span-2" title="Active Universe" neonAccent="green">
                    {isLoading ? (
                        <div className="space-y-2">
                            <Skeleton className="h-10 w-full" />
                            <Skeleton className="h-10 w-full" />
                        </div>
                    ) : activeSymbols.length === 0 ? (
                        <div className="text-zinc-500 py-8 text-center">
                            No symbols currently selected. Scanner may be initializing or in cooldown.
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                            {activeSymbols.map((symbol) => (
                                <div
                                    key={symbol}
                                    className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/40 border border-zinc-700/50"
                                >
                                    <span className="font-bold text-zinc-200">{symbol}</span>
                                    <div className="text-right">
                                        <div className="text-xs text-emerald-400 font-mono">
                                            {scores[symbol]?.toFixed(2) ?? "—"}
                                        </div>
                                        <div className="text-[10px] text-zinc-500">Score</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </GlassCard>

                {/* Highlight Card */}
                <GlassCard title="Top Performer" neonAccent="amber" className="flex flex-col justify-center items-center text-center">
                    {activeSymbols.length > 0 ? (
                        <>
                            <Trophy className="w-12 h-12 text-amber-400 mb-4" />
                            <div className="text-2xl font-bold text-zinc-100 mb-1">{activeSymbols[0]}</div>
                            <div className="text-sm text-zinc-400">Highest Rank</div>
                            <div className="mt-4 px-3 py-1 bg-amber-500/10 text-amber-400 rounded-full text-xs font-mono border border-amber-500/20">
                                Score: {scores[activeSymbols[0]]?.toFixed(4)}
                            </div>
                        </>
                    ) : (
                        <div className="text-zinc-500">No Data</div>
                    )}
                </GlassCard>
            </div>

            {/* Full Rankings Table */}
            <GlassCard title="Candidate Rankings" neonAccent="blue">
                <div className="rounded-lg overflow-hidden border border-zinc-800/50">
                    <table className="w-full text-sm text-left">
                        <thead className="bg-zinc-900/50 text-zinc-400 font-medium">
                            <tr>
                                <th className="px-4 py-3">Rank</th>
                                <th className="px-4 py-3">Symbol</th>
                                <th className="px-4 py-3 text-right">Score</th>
                                <th className="px-4 py-3 text-right">Status</th>
                                <th className="px-4 py-3 text-right">Last Selected</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/50">
                            {isLoading ? (
                                <tr><td colSpan={5} className="p-4"><Skeleton className="h-8 w-full" /></td></tr>
                            ) : rankedAll.length === 0 ? (
                                <tr><td colSpan={5} className="p-8 text-center text-zinc-500">No candidates available</td></tr>
                            ) : (
                                rankedAll.map((item, index) => (
                                    <tr key={item.symbol} className="hover:bg-zinc-800/30 transition-colors">
                                        <td className="px-4 py-3 font-mono text-zinc-500">#{index + 1}</td>
                                        <td className="px-4 py-3 font-bold text-zinc-200 flex items-center gap-2">
                                            {item.symbol}
                                            {index < 3 && <TrendingUp className="w-3 h-3 text-emerald-500" />}
                                        </td>
                                        <td className="px-4 py-3 text-right font-mono text-cyan-300">
                                            {item.score.toFixed(4)}
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            {item.isSelected ? (
                                                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                                    ACTIVE
                                                </span>
                                            ) : (
                                                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-800 text-zinc-500">
                                                    CANDIDATE
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-right text-zinc-500 text-xs font-mono">
                                            {item.lastSelected ? new Date(item.lastSelected * 1000).toLocaleTimeString() : "—"}
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </GlassCard>
        </div>
    );
}
