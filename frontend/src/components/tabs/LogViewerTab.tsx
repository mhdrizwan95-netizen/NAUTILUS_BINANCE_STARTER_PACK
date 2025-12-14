import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardContent, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';

interface LogEntry {
    ts: string;
    service: string;
    level: string;
    logger: string;
    msg: string;
    correlation_id?: string;
}

export const LogViewerTab: React.FC = () => {
    const [filter, setFilter] = useState('');
    const [autoScroll, setAutoScroll] = useState(true);
    const scrollRef = useRef<HTMLDivElement>(null);

    const { data, refetch, isError } = useQuery({
        queryKey: ['system-logs', filter],
        queryFn: async () => {
            const url = new URL('/api/logs', window.location.origin);
            url.searchParams.set('lines', '200');
            if (filter) url.searchParams.set('filter', filter);

            const res = await fetch(url.toString());
            if (!res.ok) throw new Error("Failed to fetch logs");
            return res.json() as Promise<{ logs: LogEntry[] }>;
        },
        refetchInterval: 2000, // Poll every 2s
    });

    const logs = data?.logs || [];

    // Auto-scroll to bottom
    useEffect(() => {
        if (autoScroll && scrollRef.current) {
            // Find the scroll viewport (child of ScrollArea)
            const viewport = scrollRef.current.querySelector('[data-radix-scroll-area-viewport]');
            if (viewport) {
                viewport.scrollTop = viewport.scrollHeight;
            }
        }
    }, [logs, autoScroll]);

    const getLevelColor = (level: string) => {
        switch (level) {
            case 'INFO': return 'bg-blue-500/10 text-blue-500 hover:bg-blue-500/20';
            case 'WARNING': return 'bg-yellow-500/10 text-yellow-500 hover:bg-yellow-500/20';
            case 'ERROR': return 'bg-red-500/10 text-red-500 hover:bg-red-500/20';
            case 'DEBUG': return 'bg-gray-500/10 text-gray-500 hover:bg-gray-500/20';
            default: return 'bg-gray-500/10 text-gray-500';
        }
    };

    return (
        <div className="space-y-4 h-full flex flex-col">
            <div className="flex items-center justify-between gap-4">
                <div className="flex-1 max-w-sm">
                    <Input
                        placeholder="Filter logs..."
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="bg-black/20 border-white/10"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant={autoScroll ? "default" : "outline"}
                        size="sm"
                        onClick={() => setAutoScroll(!autoScroll)}
                    >
                        {autoScroll ? "Auto-Scroll On" : "Auto-Scroll Off"}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => refetch()}>
                        Refresh
                    </Button>
                </div>
            </div>

            <Card className="flex-1 bg-black/40 border-white/5 backdrop-blur-xl overflow-hidden glass-panel">
                <CardHeader className="py-3 border-b border-white/5 bg-white/5">
                    <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium text-white/80 font-mono">
                            /var/log/system.jsonl
                        </CardTitle>
                        <div className="text-xs text-white/40 font-mono">
                            {logs.length} lines
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="p-0 h-full">
                    <ScrollArea className="h-[600px] w-full" ref={scrollRef}>
                        <div className="p-4 font-mono text-xs space-y-1">
                            {isError && (
                                <div className="text-red-400 p-2 bg-red-500/10 rounded">
                                    Failed to connect to log stream.
                                </div>
                            )}
                            {logs.map((log, i) => (
                                <div key={i} className="flex gap-2 hover:bg-white/5 p-0.5 rounded transition-colors group">
                                    <span className="text-white/30 shrink-0 w-36 select-none max-sm:hidden">
                                        {log.ts.split('T')[1]?.replace('Z', '')}
                                    </span>
                                    <span className={`w-16 shrink-0 font-bold ${log.service === 'engine' ? 'text-purple-400' : log.service === 'ops' ? 'text-cyan-400' : 'text-green-400'}`}>
                                        [{log.service}]
                                    </span>
                                    <Badge variant="outline" className={`w-16 justify-center text-[10px] h-4 border-0 ${getLevelColor(log.level)}`}>
                                        {log.level}
                                    </Badge>
                                    <span className="text-white/80 break-all whitespace-pre-wrap">
                                        {log.msg}
                                    </span>
                                </div>
                            ))}
                            {logs.length === 0 && !isError && (
                                <div className="text-white/30 text-center py-10 italic">
                                    No logs found {filter ? `matching "${filter}"` : ''}
                                </div>
                            )}
                        </div>
                    </ScrollArea>
                </CardContent>
            </Card>
        </div>
    );
};
