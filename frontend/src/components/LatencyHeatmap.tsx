/**
 * Latency Heatmap - Visualize execution speed distribution
 * 
 * Shows submit_to_ack latency patterns over time
 */
import { Activity } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useRealTimeData } from '../lib/store';
import { GlassCard } from './ui/GlassCard';
interface LatencyBucket {
    time: number;
    latency: number; // milliseconds
    frequency: number; // count
}

export function LatencyHeatmap() {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    const { latencyHistory } = useRealTimeData();
    // No local accumulation needed anymore, store handles it

    const latestHistoryRef = useRef<LatencyBucket[]>([]);

    // Keep ref in sync with store
    useEffect(() => {
        latestHistoryRef.current = latencyHistory || [];
    }, [latencyHistory]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const draw = () => {
            const width = canvas.width;
            const height = canvas.height;
            // Read from ref to avoid stale closure
            const data = latestHistoryRef.current;

            // Clear canvas
            ctx.fillStyle = 'rgba(15, 15, 35, 0.9)';
            ctx.fillRect(0, 0, width, height);

            if (data.length === 0) {
                ctx.fillStyle = '#6b7280';
                ctx.font = '14px sans-serif';
                ctx.fillText('Waiting for venue data...', width / 2 - 60, height / 2);
            } else {

                // Draw heatmap
                const cellWidth = width / 100;
                const cellHeight = height / 10;

                const now = Date.now();

                data.forEach((bucket) => {
                    const age = now - bucket.time;
                    const x = width - ((age / 100000) * width); // Right to left
                    const y = Math.min((bucket.latency / 50) * height, height - cellHeight);

                    // Color based on latency (Green -> Red)
                    // Normalize 0-50ms to 0-1
                    const severity = Math.min(bucket.latency / 50, 1);
                    const hue = 120 - (severity * 120); // 120 (Green) -> 0 (Red)

                    ctx.fillStyle = `hsla(${hue}, 100%, 50%, 0.8)`;
                    ctx.fillRect(x, y, cellWidth, cellHeight);
                });
            }

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
        };

        // Animation loop
        let animationId: number;
        const animate = () => {
            draw();
            animationId = requestAnimationFrame(animate);
        }
        animate();

        return () => cancelAnimationFrame(animationId);
    }, []);

    return (
        <GlassCard
            title="Order Latency Heatmap"
            neonAccent="blue"
            className="flex flex-col h-full" // Fill parent grid cell
            rightElement={<Activity className="h-4 w-4 text-cyber-accent" />}
        >
            <div className="relative flex-1 flex flex-col justify-center">
                <canvas
                    ref={canvasRef}
                    width={800}
                    height={200}
                    className="w-full h-full rounded border border-white/10"
                />

                {/* Legend */}
                <div className="mt-2 flex items-center justify-between text-xs text-zinc-500 font-mono">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-sm" style={{ background: 'hsl(180, 100%, 50%)' }} />
                            <span>&lt;10ms</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-sm" style={{ background: 'hsl(60, 100%, 50%)' }} />
                            <span>10-30ms</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-sm" style={{ background: 'hsl(0, 100%, 50%)' }} />
                            <span>&gt;30ms</span>
                        </div>
                    </div>
                    <div>
                        Current: {latestHistoryRef.current.length > 0 ? `${(latestHistoryRef.current[latestHistoryRef.current.length - 1].latency).toFixed(1)}ms` : '--'}
                    </div>
                </div>
            </div>
        </GlassCard>
    );
}
