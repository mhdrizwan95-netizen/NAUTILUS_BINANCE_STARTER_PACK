import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
import { TopHUD, type TopHudMetrics, type TopHudVenue } from './TopHUD';

vi.mock('./ui/switch', () => ({
  Switch: ({ checked, onCheckedChange, ...props }: any) => (
    <button
      {...props}
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
    >
      toggle
    </button>
  ),
}));

vi.mock('./ui/button', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button {...props} onClick={onClick}>
      {children}
    </button>
  ),
}));

const metrics: TopHudMetrics = {
  totalPnl: 1847.25,
  winRate: 0.62,
  sharpe: 1.45,
  maxDrawdown: 0.08,
  openPositions: 12,
};

const venues: TopHudVenue[] = [
  { name: 'Binance', status: 'ok', latencyMs: 45, queue: 2 },
  { name: 'OANDA', status: 'warn', latencyMs: 80, queue: 4 },
];

const renderHUD = (overrides: Partial<ComponentProps<typeof TopHUD>> = {}) => {
  const props: ComponentProps<typeof TopHUD> = {
    mode: 'paper',
    metrics,
    venues,
    isConnected: true,
    onModeChange: vi.fn(),
    onKillSwitch: vi.fn(),
    onPause: vi.fn(),
    onResume: vi.fn(),
    onFlatten: vi.fn(),
    ...overrides,
  };

  return { ...render(<TopHUD {...props} />), props };
};

describe('TopHUD', () => {
  it('renders branding and formatted metrics', () => {
    renderHUD();

    expect(screen.getByText('NAUTILUS')).toBeInTheDocument();
    expect(screen.getByText('TERMINAL')).toBeInTheDocument();
    expect(screen.getByText('$1,847.25')).toBeInTheDocument();
    expect(screen.getByText('62% win')).toBeInTheDocument();
    expect(screen.getByText('1.45')).toBeInTheDocument();
    expect(screen.getByText('8.00%')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('shows placeholders when metrics are loading', () => {
    renderHUD({ metrics: null, isLoading: true });

    expect(screen.getAllByText('--').length).toBeGreaterThanOrEqual(3);
  });

  it('invokes the mode change handler when toggled', async () => {
    const onModeChange = vi.fn();
    const user = userEvent.setup();
    renderHUD({ onModeChange });

    await user.click(screen.getByRole('switch', { name: /trading mode/i }));

    expect(onModeChange).toHaveBeenCalledWith('live');
  });

  it('invokes the kill switch handler', async () => {
    const onKillSwitch = vi.fn();
    const user = userEvent.setup();
    renderHUD({ onKillSwitch, onPause: vi.fn(), onResume: vi.fn(), onFlatten: vi.fn() });

    await user.click(screen.getByText('KILL'));

    expect(onKillSwitch).toHaveBeenCalled();
  });

  it('invokes pause/resume/flatten control handlers', async () => {
    const onPause = vi.fn();
    const onResume = vi.fn();
    const onFlatten = vi.fn();
    const user = userEvent.setup();
    const { rerender, props } = renderHUD({ onPause, onResume, onFlatten });

    await user.click(screen.getByText('Pause'));
    expect(onPause).toHaveBeenCalled();

    rerender(
      <TopHUD
        {...props}
        tradingEnabled={false}
      />,
    );

    await user.click(screen.getByText('Resume'));
    expect(onResume).toHaveBeenCalled();

    await user.click(screen.getByText('Flatten'));
    expect(onFlatten).toHaveBeenCalled();
  });

  it('renders venue status information', () => {
    renderHUD();

    expect(screen.getByText('Binance')).toBeInTheDocument();
    expect(screen.getByText('Healthy · 45ms · q2')).toBeInTheDocument();
    expect(screen.getByText('OANDA')).toBeInTheDocument();
    expect(screen.getByText('Degraded · 80ms · q4')).toBeInTheDocument();
  });
});
