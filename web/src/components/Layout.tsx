import React, { useState, useEffect } from 'react';
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { Select, SelectItem, Button } from '@heroui/react';
import {
  LayoutDashboard,
  FileText,
  Tag,
  Search,
  Link2,
  Network,
  FolderInput,
  GitBranch,
  Clock,
  Activity,
  Settings,
  Database,
  Sun,
  Moon,
  Plus,
} from 'lucide-react';
import { api } from '../api/client';
import { toast } from 'sonner';

export const Layout: React.FC = () => {
  const [isDark, setIsDark] = useState<boolean>(() => {
    return (
      localStorage.getItem('kb_theme') === 'dark' ||
      (!('kb_theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches) ||
      true // Default to dark for Grok aesthetic
    );
  });

  const [currentVault, setCurrentVault] = useState<string>('default');
  const [vaultList, setVaultList] = useState<string[]>([]);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('kb_theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('kb_theme', 'light');
    }
  }, [isDark]);

  const loadVaults = async () => {
    try {
      const data = await api.getVaults();
      if (data) {
        setCurrentVault(data.current_vault || 'default');
        setVaultList(data.vaults || []);
      }
    } catch {
      // fallback
    }
  };

  useEffect(() => {
    loadVaults();
  }, [location.pathname]);

  const handleSwitchVault = async (vaultName: string) => {
    if (vaultName === currentVault) return;
    try {
      await api.switchVault(vaultName);
      setCurrentVault(vaultName);
      window.location.reload();
    } catch (err: any) {
      toast.error(`Failed to switch vault: ${err.message}`);
    }
  };

  const navItems = [
    { to: '/', label: 'Overview', icon: LayoutDashboard },
    { to: '/docs', label: 'Documents', icon: FileText },
    { to: '/types', label: 'Types', icon: Tag },
    { to: '/search', label: 'Search', icon: Search },
    { to: '/links', label: 'Links', icon: Link2 },
    { to: '/graph', label: 'Graph', icon: Network },
    { to: '/imports', label: 'Imports', icon: FolderInput },
    { to: '/git', label: 'Git Sync', icon: GitBranch },
    { to: '/scheduler', label: 'Scheduler', icon: Clock },
    { to: '/health', label: 'Health & Audit', icon: Activity },
    { to: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="flex h-screen bg-[#fcfcfd] dark:bg-black text-zinc-900 dark:text-zinc-100 overflow-hidden font-sans selection:bg-zinc-200 dark:selection:bg-zinc-800 selection:text-black dark:selection:text-white">
      {/* Sleek Sidebar */}
      <aside className="w-64 flex flex-col bg-white dark:bg-[#050507] border-r border-zinc-200 dark:border-white/[0.07] shrink-0">
        {/* Logo / Header */}
        <div className="h-16 flex items-center justify-between px-5 border-b border-zinc-200 dark:border-white/[0.07]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-black dark:bg-white text-white dark:text-black flex items-center justify-center font-bold text-sm tracking-wider shadow-xs">
              ◈
            </div>
            <div>
              <div className="font-bold text-zinc-900 dark:text-white text-sm tracking-tight flex items-center gap-1.5">
                <span>kb-mcp</span>
                <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded-full bg-zinc-100 dark:bg-white/10 text-zinc-600 dark:text-zinc-300">
                  grok
                </span>
              </div>
            </div>
          </div>

          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={() => setIsDark(!isDark)}
            className="text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-white/5 rounded-full w-8 h-8"
            title="Toggle Theme"
          >
            {isDark ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-zinc-700" />}
          </Button>
        </div>

        {/* Vault Switcher */}
        <div className="px-3.5 py-3 border-b border-zinc-200 dark:border-white/[0.07] bg-zinc-50/50 dark:bg-white/[0.01]">
          <div className="text-[10px] font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-1 px-1">
            Active Vault
          </div>
          <Select
            size="sm"
            selectedKeys={currentVault ? [currentVault] : []}
            onChange={(e) => handleSwitchVault(e.target.value)}
            variant="bordered"
            startContent={<Database className="w-3.5 h-3.5 text-zinc-400" />}
            className="w-full text-xs"
            classNames={{
              trigger: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 text-xs rounded-xl min-h-9 shadow-2xs',
              value: 'text-xs text-zinc-800 dark:text-zinc-200 font-medium',
            }}
          >
            {vaultList.map((v) => (
              <SelectItem key={v} textValue={v} className="text-xs">
                {v} {v === currentVault ? '(active)' : ''}
              </SelectItem>
            ))}
          </Select>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2.5 py-3 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive =
              location.pathname === item.to ||
              (item.to !== '/' && location.pathname.startsWith(item.to));
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-zinc-100 dark:bg-white/[0.08] text-zinc-900 dark:text-white font-semibold border border-zinc-200 dark:border-white/[0.1] shadow-2xs'
                    : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100/60 dark:hover:bg-white/[0.04] hover:text-zinc-900 dark:hover:text-zinc-100'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-zinc-900 dark:text-white' : 'text-zinc-400 dark:text-zinc-500'}`} />
                <span>{item.label}</span>
                {isActive && <div className="ml-auto w-1.5 h-1.5 rounded-full bg-zinc-900 dark:bg-white" />}
              </NavLink>
            );
          })}
        </nav>

        {/* Quick Action & Status Footer */}
        <div className="p-3.5 border-t border-zinc-200 dark:border-white/[0.07] space-y-2">
          <Button
            size="sm"
            onPress={() => navigate('/docs')}
            startContent={<Plus className="w-3.5 h-3.5" />}
            className="w-full bg-black dark:bg-white text-white dark:text-black font-semibold text-xs hover:bg-zinc-800 dark:hover:bg-zinc-200 rounded-full h-9 shadow-sm"
          >
            New Document
          </Button>

          <div className="flex items-center justify-between px-2 pt-1 text-[11px] text-zinc-400 dark:text-zinc-500 font-mono">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Connected
            </span>
            <span>v1.0</span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#fcfcfd] dark:bg-black overflow-y-auto">
        <div className="p-6 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
