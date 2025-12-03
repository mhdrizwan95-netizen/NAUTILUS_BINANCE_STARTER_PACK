/**
 * Canvas Price Chart - High-performance charting for real-time price data
 * 
 * Uses Lightweight Charts (TradingView) for smooth rendering of 100k+ candlesticks
 */
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import { useEffect, useRef } from 'react';

interface Candle {
    time: number; // Unix timestamp
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
}

interface CanvasPriceChartProps {
    data: Candle[];
    symbol: string;
    height?: number;
}

export function CanvasPriceChart({ data, symbol, height = 400 }: CanvasPriceChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        // Create chart with cyberpunk theme
        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#e0e6ff',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            width: chartContainerRef.current.clientWidth,
            height,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
            crosshair: {
                vertLine: {
                    color: '#00ff9d',
                    width: 1,
                    style: 3,
                },
                horzLine: {
                    color: '#00ff9d',
                    width: 1,
                    style: 3,
                },
            },
        });

        // Add candlestick series
        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#00ff9d', // Neon green
            downColor: '#ff6b6b', // Neon red
            borderUpColor: '#00ff9d',
            borderDownColor: '#ff6b6b',
            wickUpColor: '#00ff9d',
            wickDownColor: '#ff6b6b',
        });

        chartRef.current = chart;
        seriesRef.current = candlestickSeries;

        // Handle resize
        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [height]);

    // Update data when it changes
    useEffect(() => {
        if (seriesRef.current && data.length > 0) {
            // Cast timestamps to Time type (seconds)
            const formattedData = data.map(candle => ({
                ...candle,
                time: (candle.time / 1000) as Time, // Convert ms to seconds and cast
            }));

            seriesRef.current.setData(formattedData);

            // Fit content to visible range
            if (chartRef.current) {
                chartRef.current.timeScale().fitContent();
            }
        }
    }, [data]);

    return (
        <div className="glass-panel h-full flex flex-col">
            <div className="px-4 py-2 border-b border-cyber-glass-border">
                <h3 className="text-sm font-medium cyber-positive">{symbol}</h3>
                <p className="text-xs text-cyber-text-dim">{data.length.toLocaleString()} candles</p>
            </div>
            <div ref={chartContainerRef} className="flex-1" />
        </div>
    );
}
