/**
 * Latency Heatmap - Visualize execution speed distribution
 * 
 * Shows submit_to_ack latency patterns over time
 */
import { Activity } from 'lucide-react';
import { useEffect, useRef } from 'react';

interface LatencyBucket {
    time: number;
    latency: number; // milliseconds
    frequency: number; // count
}

export function LatencyHeatmap() {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    // Mock data - in production, fetch from tradingStore or API
    const generateMockData = (): LatencyBucket[] => {
        const data: LatencyBucket[] = [];
        const now = Date.now();

        for (let i = 0; i < 100; i++) {
            const time = now - i * 1000; // Last 100 seconds
            for (let lat = 0; lat < 50; lat += 5) {
                data.push({
                    time,
                    latency: lat,
                    frequency: Math.random() * 10 * Math.exp(-(lat / 20)), // More frequent at lower latencies
                });
            }
        }
        return data;
    };

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const data = generateMockData();
        const width = canvas.width;
        const height = canvas.height;

        // Clear canvas
        ctx.fillStyle = 'rgba(15, 15, 35, 0.9)';
        ctx.fillRect(0, 0, width, height);

        // Draw heatmap
        const cellWidth = width / 100;
        const cellHeight = height / 10;

        data.forEach((bucket) => {
            const x = ((Date.now() - bucket.time) / 100000) * width;
            const y = (bucket.latency / 50) * height;

            // Color based on frequency (hot = more frequent)
            const intensity = Math.min(bucket.frequency / 10, 1);
            const hue = 180 - intensity * 180; // Green to red
            ctx.fillStyle = `hsla(${hue}, 100%, 50%, ${intensity * 0.7})`;

            ctx.fillRect(x, y, cellWidth, cellHeight);
        });

        // Draw grid lines
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
        ctx.lineWidth = 1;

        // Horizontal lines (latency levels)
        for (let i = 0; i <= 10; i++) {
            const y = (i / 10) * height;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
            ctx.stroke();
        }

        // Labels
        ctx.fillStyle = '#e0e6ff';
        ctx.font = '10px monospace';
        ctx.fillText('0ms', 5, height - 5);
        ctx.fillText('50ms', 5, 15);
    }, []);

    return (
        <div className="glass-panel p-4">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-sm font-medium cyber-positive">Execution Latency Heatmap</h3>
                    <p className="text-xs text-cyber-text-dim">submit_to_ack distribution over time</p>
                </div>
                <Activity className="h-4 w-4 text-cyber-accent" />
            </div>

            <div className="relative">
                <canvas
                    ref={canvasRef}
                    width={800}
                    height={200}
                    className="w-full rounded border border-cyber-glass-border"
                />

                {/* Legend */}
                <div className="mt-2 flex items-center gap-4 text-xs text-cyber-text-dim">
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded" style={{ background: 'hsl(180, 100%, 50%)' }} />
                        <span>Fast (&lt;10ms)</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded" style={{ background: 'hsl(60, 100%, 50%)' }} />
                        <span>Normal (10-30ms)</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded" style={{ background: 'hsl(0, 100%, 50%)' }} />
                        <span>Slow (&gt;30ms)</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
