import { useEffect, useState, useMemo } from 'react';
import { TopHUD } from './components/TopHUD';
import { TabbedInterface } from './components/TabbedInterface';
import { Toaster } from './components/ui/sonner';
import { toast } from 'sonner';
import { generatePerformanceData, getGlobalMetrics } from './lib/mockData';
import { useAppStore, useModeActions, useRealTimeActions } from './lib/store';
import { useWebSocket } from './lib/websocket';
import { motion } from 'motion/react';

export default function App() {
  const [isBooting, setIsBooting] = useState(true);
  const mode = useAppStore((state) => state.mode);
  const realTimeData = useAppStore((state) => state.realTimeData);
  const { setMode } = useModeActions();
  const { updatePerformances, updateGlobalMetrics: updateStoreMetrics } = useRealTimeActions();

  // WebSocket connection for real-time updates
  const { isConnected } = useWebSocket();

  // Memoize derived data to prevent unnecessary recalculations
  const performances = useMemo(() =>
    realTimeData.performances.length > 0
      ? realTimeData.performances
      : generatePerformanceData(),
    [realTimeData.performances]
  );

  const globalMetrics = useMemo(() =>
    realTimeData.globalMetrics || getGlobalMetrics(performances),
    [realTimeData.globalMetrics, performances]
  );

  // Boot sequence animation
  useEffect(() => {
    const timer = setTimeout(() => {
      setIsBooting(false);
      toast.info('Nautilus Terminal Online', {
        description: 'All systems operational',
      });
    }, 1500);
    return () => clearTimeout(timer);
  }, []);

  // Simulate live updates - use refs to avoid dependency issues
  useEffect(() => {
    if (isBooting) return;

    const interval = setInterval(() => {
      const newPerformances = generatePerformanceData();
      const newMetrics = getGlobalMetrics(newPerformances);
      updatePerformances(newPerformances);
      updateStoreMetrics(newMetrics);
    }, 5000);

    return () => clearInterval(interval);
  }, [isBooting]); // Only depend on isBooting

  const handleModeChange = (newMode: typeof mode) => {
    setMode(newMode);
    toast.success(`Switched to ${newMode.toUpperCase()} mode`, {
      description: newMode === 'live' ? 'Real capital at risk' : 'Simulated trading active',
    });
  };

  const handleKillSwitch = () => {
    toast.error('EMERGENCY STOP ACTIVATED', {
      description: 'All positions closed, trading halted',
    });
  };

  if (isBooting) {
    return (
      <div className="h-screen bg-zinc-950 flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center"
        >
          <motion.div
            className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-400 via-violet-400 to-indigo-500 relative"
            animate={{
              boxShadow: [
                '0 0 20px rgba(0, 245, 212, 0.3)',
                '0 0 40px rgba(0, 245, 212, 0.5)',
                '0 0 20px rgba(0, 245, 212, 0.3)',
              ],
            }}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="text-zinc-100 mb-2"
          >
            NAUTILUS TERMINAL
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            className="text-zinc-500 text-sm tracking-wider"
          >
            INITIALIZING NEURAL NETWORK...
          </motion.p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-zinc-950 flex flex-col overflow-hidden dark">
      {/* Top HUD */}
      <TopHUD isConnected={isConnected} />

      {/* Tabbed Interface */}
      <TabbedInterface />

      {/* Toast Notifications */}
      <Toaster />
    </div>
  );
}
