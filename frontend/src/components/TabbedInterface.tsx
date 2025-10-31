import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { LayoutDashboard, Target, Wallet, Brain, Settings } from 'lucide-react';
import { DashboardTab } from './tabs/DashboardTab';
import { StrategyTab } from './tabs/StrategyTab';
import { FundingTab } from './tabs/FundingTab';
import { BacktestingTab } from './tabs/BacktestingTab';
import { SettingsTab } from './tabs/SettingsTab';
import { motion } from 'motion/react';

export function TabbedInterface() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.1 }}
      className="flex-1 flex flex-col border-t border-zinc-800/50 bg-zinc-900/40 backdrop-blur-sm overflow-hidden"
    >
      <Tabs defaultValue="dashboard" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="w-full justify-start border-b border-zinc-800/50 bg-transparent rounded-none px-8 h-12 flex-shrink-0">
          <TabsTrigger 
            value="dashboard" 
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>Dashboard</span>
          </TabsTrigger>
          <TabsTrigger 
            value="strategy" 
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Target className="w-4 h-4" />
            <span>Strategy</span>
          </TabsTrigger>
          <TabsTrigger 
            value="funding" 
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Wallet className="w-4 h-4" />
            <span>Funding</span>
          </TabsTrigger>
          <TabsTrigger 
            value="backtesting" 
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Brain className="w-4 h-4" />
            <span>Backtesting / ML</span>
          </TabsTrigger>
          <TabsTrigger 
            value="settings" 
            className="gap-2 data-[state=active]:bg-zinc-800/50 data-[state=active]:text-cyan-400 data-[state=active]:border-b-2 data-[state=active]:border-cyan-400 rounded-t-lg rounded-b-none"
          >
            <Settings className="w-4 h-4" />
            <span>Settings</span>
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-auto">
          <TabsContent value="dashboard" className="m-0 h-full">
            <DashboardTab />
          </TabsContent>

          <TabsContent value="strategy" className="m-0 h-full">
            <StrategyTab />
          </TabsContent>

          <TabsContent value="funding" className="m-0 h-full">
            <FundingTab />
          </TabsContent>

          <TabsContent value="backtesting" className="m-0 h-full">
            <BacktestingTab />
          </TabsContent>

          <TabsContent value="settings" className="m-0 h-full">
            <SettingsTab />
          </TabsContent>
        </div>
      </Tabs>
    </motion.div>
  );
}
