import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import * as StoreModule from '../lib/store';
import { TopHUD } from './TopHUD';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the store hooks
vi.mock('../lib/store', () => ({
  useAppStore: vi.fn(() => ({
    mode: 'paper',
    realTimeData: {
      globalMetrics: {
        totalPnL: 1250.50,
        totalPnLPercent: 12.55,
        sharpe: 1.8,
        drawdown: 0.05,
        activePositions: 3,
        dailyTradeCount: 15,
      },
      performances: [],
      venues: [
        { id: 'binance', name: 'Binance', type: 'crypto', status: 'connected', latency: 45 },
        { id: 'bybit', name: 'Bybit', type: 'crypto', status: 'connected', latency: 52 },
      ],
      lastUpdate: Date.now(),
    },
  })),
  useRealTimeData: vi.fn(() => ({
    globalMetrics: {
      totalPnL: 1250.50,
      totalPnLPercent: 12.55,
      sharpe: 1.8,
      drawdown: 0.05,
      activePositions: 3,
      dailyTradeCount: 15,
    },
    performances: [],
    venues: [
      { id: 'binance', name: 'Binance', type: 'crypto', status: 'connected', latency: 45 },
      { id: 'bybit', name: 'Bybit', type: 'crypto', status: 'connected', latency: 52 },
    ],
    lastUpdate: Date.now(),
  })),
  useModeActions: vi.fn(() => ({
    setMode: vi.fn(),
  })),
  useRealTimeActions: vi.fn(() => ({
    updateVenues: vi.fn(),
  })),
}));

vi.mock('../lib/websocket', () => ({
  useWebSocket: vi.fn(() => ({
    isConnected: true,
    lastMessage: null,
    sendMessage: vi.fn(),
    reconnect: vi.fn(),
  })),
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Power: () => <div data-testid="power-icon">Power</div>,
  Activity: () => <div data-testid="activity-icon">Activity</div>,
  Wifi: () => <div data-testid="wifi-icon">Wifi</div>,
  WifiOff: () => <div data-testid="wifi-off-icon">WifiOff</div>,
}));

// Mock UI components
vi.mock('./ui/switch', () => ({
  Switch: ({ checked, onCheckedChange }: any) => (
    <button
      data-testid="mode-switch"
      data-checked={checked}
      onClick={() => onCheckedChange(!checked)}
    >
      Switch
    </button>
  ),
}));

vi.mock('./ui/button', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props} data-testid="button">
      {children}
    </button>
  ),
}));

describe('TopHUD Component', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  const renderWithProviders = (component: React.ReactElement) => {
    return render(
      <QueryClientProvider client={queryClient}>
        {component}
      </QueryClientProvider>
    );
  };

  it('should render the branding and connection status', () => {
    renderWithProviders(<TopHUD isConnected />);

    expect(screen.getByText('NAUTILUS')).toBeInTheDocument();
    expect(screen.getByText('TERMINAL')).toBeInTheDocument();
    expect(screen.getByTestId('wifi-icon')).toBeInTheDocument();
  });

  it('should display global metrics', () => {
    renderWithProviders(<TopHUD />);

    expect(screen.getByText('$1,250.50')).toBeInTheDocument();
    expect(screen.getByText('+12.55%')).toBeInTheDocument();
    expect(screen.getByText('1.80')).toBeInTheDocument();
    expect(screen.getByText('5.00%')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('should display venue indicators', () => {
    renderWithProviders(<TopHUD />);

    expect(screen.getByText('Binance')).toBeInTheDocument();
    expect(screen.getByText('Bybit')).toBeInTheDocument();
    expect(screen.getAllByText(/ms/)).toHaveLength(2);
  });

  it('should show mode toggle', () => {
    renderWithProviders(<TopHUD />);

    expect(screen.getByText('PAPER')).toBeInTheDocument();
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(screen.getByTestId('mode-switch')).toBeInTheDocument();
  });

  it('should show kill switch button', () => {
    renderWithProviders(<TopHUD />);

    expect(screen.getByText('KILL')).toBeInTheDocument();
    expect(screen.getByTestId('power-icon')).toBeInTheDocument();
  });

  it('should not render when metrics are not available', () => {
    // Mock empty metrics
    vi.spyOn(StoreModule, 'useAppStore' as any).mockReturnValue({
      mode: 'paper',
      realTimeData: {
        globalMetrics: null,
        performances: [],
        venues: [],
        lastUpdate: null,
      },
    });
    vi.spyOn(StoreModule, 'useRealTimeData' as any).mockReturnValue({
      globalMetrics: null,
      performances: [],
      venues: [],
      lastUpdate: null,
    });

    const { container } = renderWithProviders(<TopHUD />);
    expect(container.firstChild).toBeNull();
  });

  it('should display fallback venues when real-time data is empty', () => {
    // Mock empty venues but with metrics
    vi.spyOn(StoreModule, 'useAppStore' as any).mockReturnValue({
      mode: 'paper',
      realTimeData: {
        globalMetrics: {
          totalPnL: 1000,
          totalPnLPercent: 10,
          sharpe: 1.5,
          drawdown: 0.05,
          activePositions: 2,
          dailyTradeCount: 10,
        },
        performances: [],
        venues: [], // Empty venues
        lastUpdate: Date.now(),
      },
    });
    vi.spyOn(StoreModule, 'useRealTimeData' as any).mockReturnValue({
      globalMetrics: {
        totalPnL: 1000,
        totalPnLPercent: 10,
        sharpe: 1.5,
        drawdown: 0.05,
        activePositions: 2,
        dailyTradeCount: 10,
      },
      performances: [],
      venues: [], // Empty venues
      lastUpdate: Date.now(),
    });

    renderWithProviders(<TopHUD />);

    // Should show fallback venues
    expect(screen.getByText('Binance')).toBeInTheDocument();
    expect(screen.getByText('IBKR')).toBeInTheDocument();
  });
});
