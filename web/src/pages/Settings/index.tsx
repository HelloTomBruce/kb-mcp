import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Input,
  Spinner,
  Progress,
} from '@heroui/react';
import {
  Settings,
  Database,
  Plus,
  FileCode,
  Save,
  Sparkles,
  Check,
  CheckCircle2,
  AlertCircle,
  Terminal,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';

interface ReindexLogItem {
  time: string;
  doc_id: string;
  status: 'ok' | 'failed';
  index: number;
  total: number;
}

export const SettingsPage: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [newVaultName, setNewVaultName] = useState('');
  const [configContent, setConfigContent] = useState('');
  const [configPath, setConfigPath] = useState('');

  // Reindex embedding progress states
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexProgress, setReindexProgress] = useState<{
    processed: number;
    total: number;
    currentDocId: string;
    succeeded: number;
    failed: number;
    dim?: number;
    isFinished: boolean;
    error?: string;
  } | null>(null);
  const [reindexLogs, setReindexLogs] = useState<ReindexLogItem[]>([]);
  const [showLogs, setShowLogs] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (isReindexing && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [reindexLogs, isReindexing]);

  const switchMutation = useMutation({
    mutationFn: (name: string) => api.switchVault(name),
    onSuccess: () => {
      queryClient.invalidateQueries();
      window.location.reload();
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const saveConfigMutation = useMutation({
    mutationFn: () => api.saveConfig(configContent),
    onSuccess: () => toast.success(t('settings.saveConfigSuccess')),
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
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
      toast.success(t('common.success'));
    } catch (err: any) {
      toast.error(`${t('common.failed')}: ${err.message}`);
    }
  };

  const handleReindexEmbeddings = async () => {
    if (isReindexing) return;
    setIsReindexing(true);
    setReindexLogs([]);
    setReindexProgress({
      processed: 0,
      total: 0,
      currentDocId: '',
      succeeded: 0,
      failed: 0,
      isFinished: false,
    });

    try {
      const response = await fetch('/api/vaults/embed?stream=1', {
        method: 'POST',
        headers: {
          Accept: 'text/event-stream',
        },
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || 'Failed to start embedding reindex');
      }

      if (!response.body) {
        throw new Error('ReadableStream not supported');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let successCount = 0;
      let failCount = 0;

      const processEvent = (rawChunk: string) => {
        const trimmed = rawChunk.trim();
        if (!trimmed.startsWith('data:')) return;
        const jsonStr = trimmed.slice(5).trim();
        if (!jsonStr) return;
        try {
          const event = JSON.parse(jsonStr);
          if (event.type === 'progress') {
            if (event.status === 'ok') successCount++;
            else failCount++;

            setReindexProgress({
              processed: event.processed,
              total: event.total,
              currentDocId: event.doc_id,
              succeeded: successCount,
              failed: failCount,
              isFinished: false,
            });

            const now = new Date().toLocaleTimeString();
            setReindexLogs((prev) => [
              ...prev.slice(-100),
              {
                time: now,
                doc_id: event.doc_id,
                status: event.status,
                index: event.processed,
                total: event.total,
              },
            ]);
          } else if (event.type === 'complete') {
            setReindexProgress((_prev) => ({
              processed: event.total || _prev?.processed || 0,
              total: event.total || _prev?.total || 0,
              currentDocId: '',
              succeeded: event.reindexed,
              failed: event.failed,
              dim: event.dim,
              isFinished: true,
            }));
            toast.success(
              t('settings.reindexSuccess', {
                reindexed: event.reindexed,
                failed: event.failed,
              })
            );
          } else if (event.type === 'error') {
            setReindexProgress((prev) => ({
              processed: prev?.processed || 0,
              total: prev?.total || 0,
              currentDocId: '',
              succeeded: successCount,
              failed: failCount,
              isFinished: true,
              error: event.error,
            }));
            toast.error(`Embeddings error: ${event.error}`);
          }
        } catch (err) {
          console.error('Failed to parse SSE line:', rawChunk, err);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          processEvent(line);
        }
      }

      if (buffer.trim()) {
        processEvent(buffer);
      }
    } catch (err: any) {
      setReindexProgress((prev) => ({
        processed: prev?.processed || 0,
        total: prev?.total || 0,
        currentDocId: '',
        succeeded: prev?.succeeded || 0,
        failed: prev?.failed || 0,
        isFinished: true,
        error: err.message,
      }));
      toast.error(`${t('common.failed')}: ${err.message}`);
    } finally {
      setIsReindexing(false);
    }
  };

  const isLoading = isVaultsLoading || isConfigLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label={t('settings.loadingSettings')} />
      </div>
    );
  }

  const currentVault = vaultsData?.current_vault || 'default';
  const vaultList = vaultsData?.vaults || ['default'];

  const percent =
    reindexProgress && reindexProgress.total > 0
      ? Math.min(100, Math.round((reindexProgress.processed / reindexProgress.total) * 100))
      : 0;

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Top Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
          <Settings className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
          {t('settings.title')}
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          {t('settings.subtitle')}
        </p>
      </div>

      {/* Vault Management */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <Database className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              {t('settings.vaultsTitle')}
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              {t('settings.vaultsDesc')}
            </p>
          </div>

          <Button
            size="sm"
            isLoading={isReindexing}
            startContent={!isReindexing ? <Sparkles className="w-3.5 h-3.5" /> : undefined}
            onPress={handleReindexEmbeddings}
            className="bg-zinc-100 hover:bg-zinc-200 text-zinc-800 border-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] dark:text-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-8 px-4 shrink-0 shadow-2xs"
          >
            {isReindexing ? t('settings.reindexing') : t('settings.reindex')}
          </Button>
        </div>

        {/* Real-time Reindexing Progress Box */}
        {reindexProgress && (
          <div className="rounded-xl p-4 bg-zinc-50 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/[0.08] space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {isReindexing ? (
                  <Spinner size="sm" />
                ) : reindexProgress.error ? (
                  <AlertCircle className="w-4 h-4 text-red-500" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                )}
                <span className="text-xs font-semibold text-zinc-900 dark:text-white">
                  {isReindexing
                    ? t('settings.reindexInProgress')
                    : reindexProgress.error
                    ? `Error: ${reindexProgress.error}`
                    : t('settings.reindexCompleted')}
                </span>
              </div>

              {/* Stats badges */}
              <div className="flex items-center gap-3 text-xs font-mono">
                <span className="text-zinc-500 dark:text-zinc-400">
                  {t('settings.processedDocs')}:{' '}
                  <strong className="text-zinc-900 dark:text-zinc-200">
                    {reindexProgress.processed} / {reindexProgress.total}
                  </strong>
                </span>
                <span className="text-emerald-600 dark:text-emerald-400">
                  {t('settings.successCount')}: <strong>{reindexProgress.succeeded}</strong>
                </span>
                {reindexProgress.failed > 0 && (
                  <span className="text-red-500">
                    {t('settings.failCount')}: <strong>{reindexProgress.failed}</strong>
                  </span>
                )}
                <span className="font-bold text-zinc-900 dark:text-zinc-100">{percent}%</span>
              </div>
            </div>

            {/* Progress Bar */}
            <Progress
              size="sm"
              value={percent}
              color={reindexProgress.error ? 'danger' : isReindexing ? 'primary' : 'success'}
              className="w-full"
              aria-label="Reindex progress"
            />

            {/* Current Processing Doc & Hints */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400 gap-2">
              <div className="font-mono truncate">
                {isReindexing && reindexProgress.currentDocId ? (
                  <span>{t('settings.reindexDocProcessing', { docId: reindexProgress.currentDocId })}</span>
                ) : (
                  <span>{t('settings.reindexHint')}</span>
                )}
              </div>

              {reindexLogs.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowLogs(!showLogs)}
                  className="flex items-center gap-1 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors shrink-0"
                >
                  <Terminal className="w-3.5 h-3.5" />
                  <span>{t('settings.reindexDetails')} ({reindexLogs.length})</span>
                  {showLogs ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
              )}
            </div>

            {/* Realtime Terminal / Log Stream */}
            {showLogs && reindexLogs.length > 0 && (
              <div className="rounded-lg bg-zinc-950 p-3 max-h-48 overflow-y-auto font-mono text-[11px] text-zinc-300 space-y-1 border border-zinc-800">
                {reindexLogs.map((log, idx) => (
                  <div key={idx} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 truncate">
                      <span className="text-zinc-500 select-none">[{log.time}]</span>
                      <span
                        className={`px-1 rounded-sm text-[10px] uppercase font-bold ${
                          log.status === 'ok'
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/40'
                            : 'bg-red-950 text-red-400 border border-red-800/40'
                        }`}
                      >
                        {log.status}
                      </span>
                      <span className="text-zinc-200 truncate">{log.doc_id}</span>
                    </div>
                    <span className="text-zinc-500 text-[10px] shrink-0">
                      {log.index}/{log.total}
                    </span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}
          </div>
        )}

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
                      <Check className="w-3 h-3" /> {t('settings.activeBadge')}
                    </span>
                  ) : (
                    <span className="text-[10px] text-zinc-500 font-mono">{t('settings.switchBadge')}</span>
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
            placeholder={t('settings.vaultPlaceholder')}
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
            {t('settings.createVault')}
          </Button>
        </form>
      </div>

      {/* Global Configuration File (config.yaml) */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <FileCode className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              {t('settings.globalConfig')}
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
            {t('settings.saveConfig')}
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
