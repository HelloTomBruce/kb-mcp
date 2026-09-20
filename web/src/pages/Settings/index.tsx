import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Input,
  Spinner,
} from '@heroui/react';
import {
  Settings,
  Database,
  Plus,
  FileCode,
  Save,
  Sparkles,
  Check,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';

export const SettingsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [newVaultName, setNewVaultName] = useState('');
  const [configContent, setConfigContent] = useState('');
  const [configPath, setConfigPath] = useState('');

  const { data: vaultsData, isLoading: isVaultsLoading } = useQuery({
    queryKey: ['vaults'],
    queryFn: () => api.getVaults(),
  });

  const { data: configData, isLoading: isConfigLoading } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.getConfig(),
  });

  useEffect(() => {
    if (configData) {
      setConfigContent(configData.content || '');
      setConfigPath(configData.path || '');
    }
  }, [configData]);

  const switchMutation = useMutation({
    mutationFn: (name: string) => api.switchVault(name),
    onSuccess: () => {
      queryClient.invalidateQueries();
      window.location.reload();
    },
    onError: (err: any) => toast.error(`Failed to switch vault: ${err.message}`),
  });

  const saveConfigMutation = useMutation({
    mutationFn: () => api.saveConfig(configContent),
    onSuccess: () => toast.success('Configuration file saved successfully.'),
    onError: (err: any) => toast.error(`Failed to save configuration: ${err.message}`),
  });

  const handleCreateVault = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newVaultName.trim()) return;
    try {
      await fetch('/api/vaults', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newVaultName.trim() }),
      });
      setNewVaultName('');
      queryClient.invalidateQueries({ queryKey: ['vaults'] });
      toast.success(`Vault "${newVaultName}" created.`);
    } catch (err: any) {
      toast.error(`Create vault failed: ${err.message}`);
    }
  };

  const handleReindexEmbeddings = async () => {
    try {
      const res = await fetch('/api/vaults/embed', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        toast.success(`Embeddings reindexed. Total processed: ${data.reindexed}, Failed: ${data.failed}`);
      } else {
        toast.error(`Embeddings error: ${data.error}`);
      }
    } catch (err: any) {
      toast.error(`Reindex failed: ${err.message}`);
    }
  };

  const isLoading = isVaultsLoading || isConfigLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label="Loading system settings..." />
      </div>
    );
  }

  const currentVault = vaultsData?.current_vault || 'default';
  const vaultList = vaultsData?.vaults || ['default'];

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
          <Settings className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
          Settings & Vaults
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          Manage isolated knowledge repositories (Multi-Vault), vector indices, and system config file
        </p>
      </div>

      {/* Vault Management */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <Database className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Active Knowledge Vaults
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              Each vault operates as an isolated single-file SQLite database with its own FTS and semantic vectors.
            </p>
          </div>

          <Button
            size="sm"
            startContent={<Sparkles className="w-3.5 h-3.5" />}
            onPress={handleReindexEmbeddings}
            className="bg-zinc-100 hover:bg-zinc-200 text-zinc-800 border-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] dark:text-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-8 px-4"
          >
            Reindex Vector Embeddings
          </Button>
        </div>

        {/* Vault Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {vaultList.map((v) => {
            const isActive = v === currentVault;
            return (
              <div
                key={v}
                onClick={() => {
                  if (!isActive) switchMutation.mutate(v);
                }}
                className={`p-4 rounded-xl border transition-all cursor-pointer flex flex-col justify-between gap-3 ${
                  isActive
                    ? 'bg-zinc-100 dark:bg-white/[0.08] border-zinc-400 dark:border-white/20 shadow-xs'
                    : 'bg-zinc-50/50 dark:bg-white/[0.02] border-zinc-200 dark:border-white/[0.06] hover:bg-zinc-100/80 dark:hover:bg-white/[0.05] hover:border-zinc-300 dark:hover:border-white/[0.1]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100 font-mono truncate">
                    {v}
                  </span>
                  {isActive ? (
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/40">
                      <Check className="w-3 h-3" /> Active
                    </span>
                  ) : (
                    <span className="text-[10px] text-zinc-500 font-mono">Switch</span>
                  )}
                </div>
                <div className="text-[11px] text-zinc-500 font-mono truncate">
                  ~/.local/share/kb/{v}.db
                </div>
              </div>
            );
          })}
        </div>

        {/* Create Vault */}
        <form onSubmit={handleCreateVault} className="pt-2 flex items-center gap-3">
          <Input
            size="sm"
            variant="bordered"
            value={newVaultName}
            onValueChange={setNewVaultName}
            placeholder="Create new isolated vault (e.g. personal, devops)..."
            className="flex-1 font-mono text-xs"
            classNames={{
              inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-10 text-xs shadow-2xs',
              input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
            }}
          />
          <Button
            type="submit"
            size="sm"
            startContent={<Plus className="w-4 h-4" />}
            className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-10 px-5 shadow-sm shrink-0"
          >
            Create Vault
          </Button>
        </form>
      </div>

      {/* Global Configuration File (config.yaml) */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <FileCode className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Global Settings Configuration
            </h2>
            <div className="text-xs font-mono text-zinc-500 mt-1">
              File: {configPath || '~/.config/kb/config.yaml'}
            </div>
          </div>

          <Button
            size="sm"
            startContent={<Save className="w-3.5 h-3.5" />}
            isLoading={saveConfigMutation.isPending}
            onPress={() => saveConfigMutation.mutate()}
            className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
          >
            Save Configuration
          </Button>
        </div>

        <div className="rounded-xl overflow-hidden border border-zinc-200 dark:border-white/[0.08] bg-zinc-950">
          <textarea
            value={configContent}
            onChange={(e) => setConfigContent(e.target.value)}
            rows={14}
            className="w-full p-4 font-mono text-xs bg-zinc-950 text-zinc-200 focus:outline-hidden resize-y leading-relaxed"
            placeholder="# Enter valid YAML configuration..."
            spellCheck={false}
          />
        </div>
      </div>
    </div>
  );
};
