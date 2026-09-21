import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Input,
  Spinner,
  Tabs,
  Tab,
} from '@heroui/react';
import {
  GitBranch,
  GitCommit,
  RefreshCw,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  AlertCircle,
  FolderGit2,
  FileCode,
  Database,
  Plus,
  Edit3,
  Trash2,
  Eye,
  EyeOff,
  Code2,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { DiffViewer } from '../../components/DiffViewer';

interface DiffTarget {
  type: 'all' | 'file' | 'doc';
  name?: string;
  staged?: boolean;
  label?: string;
}

export const GitPage: React.FC = () => {
  const { t } = useTranslation();
  const [commitMessage, setCommitMessage] = useState('');
  const [syncDir, setSyncDir] = useState('');
  const [remoteBranch, setRemoteBranch] = useState('main');
  const [remoteName, setRemoteName] = useState('origin');
  const [selectedDiffTarget, setSelectedDiffTarget] = useState<DiffTarget | null>(null);

  const { data: gitStatus, isLoading: isStatusLoading, refetch: refetchStatus } = useQuery({
    queryKey: ['git-status'],
    queryFn: () => api.getGitStatus(),
  });

  const { data: gitHistory, isLoading: isHistoryLoading, refetch: refetchHistory } = useQuery({
    queryKey: ['git-history'],
    queryFn: () => api.getGitHistory(30),
  });

  const { data: diffData, isLoading: isDiffLoading, refetch: refetchDiff } = useQuery({
    queryKey: ['git-diff', selectedDiffTarget],
    queryFn: () => {
      if (!selectedDiffTarget) return null;
      if (selectedDiffTarget.type === 'doc') {
        return api.getGitDiff({ doc_id: selectedDiffTarget.name });
      }
      if (selectedDiffTarget.type === 'file') {
        return api.getGitDiff({ path: selectedDiffTarget.name, staged: selectedDiffTarget.staged });
      }
      return api.getGitDiff();
    },
    enabled: !!selectedDiffTarget,
  });

  const refreshAll = () => {
    refetchStatus();
    refetchHistory();
    if (selectedDiffTarget) refetchDiff();
  };

  const commitMutation = useMutation({
    mutationFn: (msg: string) => api.gitCommit(msg),
    onSuccess: (data) => {
      setCommitMessage('');
      setSelectedDiffTarget(null);
      refreshAll();
      toast.success(`${t('common.success')}: ${data.output || 'OK'}`);
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const syncMutation = useMutation({
    mutationFn: () => api.gitSync('sync: admin auto-commit'),
    onSuccess: (data) => {
      setSelectedDiffTarget(null);
      refreshAll();
      toast.success(`${t('common.success')}: ${data.output || 'OK'}`);
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const pullMutation = useMutation({
    mutationFn: (branchToPull?: string) =>
      api.gitPull(remoteName.trim() || 'origin', (branchToPull || remoteBranch).trim() || 'main'),
    onSuccess: (data) => {
      refreshAll();
      toast.success(`${t('common.success')}: ${data?.output || 'Up to date'}`);
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const pushMutation = useMutation({
    mutationFn: (branchToPush?: string) =>
      api.gitPush(remoteName.trim() || 'origin', (branchToPush || remoteBranch).trim() || 'main'),
    onSuccess: (data) => {
      refreshAll();
      toast.success(`${t('common.success')}: ${data?.output || 'OK'}`);
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const initMutation = useMutation({
    mutationFn: () => api.gitInit(syncDir || undefined),
    onSuccess: () => {
      refreshAll();
      toast.success(t('common.success'));
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const isLoading = isStatusLoading || isHistoryLoading;
  const isGit = gitStatus?.is_git !== false && gitStatus?.ok;

  const pendingExport = gitStatus?.pending_export || { total: 0, added: [], modified: [], deleted: [] };
  const staged = gitStatus?.staged || [];
  const unstaged = gitStatus?.unstaged || [];
  const untracked = gitStatus?.untracked || [];

  const totalPendingChanges =
    (pendingExport.total || 0) + staged.length + unstaged.length + untracked.length;
  const isClean = gitStatus?.clean ?? totalPendingChanges === 0;

  const activeDiffText = (() => {
    if (!selectedDiffTarget || !diffData) return '';
    if (selectedDiffTarget.type === 'doc' && selectedDiffTarget.name) {
      return diffData.pending_diffs?.[selectedDiffTarget.name] || diffData.diff || '';
    }
    return diffData.diff || '';
  })();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label={t('git.checkingStatus')} />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <GitBranch className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            {t('git.title')}
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            {t('git.subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={refreshAll}
            className="text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-full w-8 h-8"
            title={t('git.refreshStatus')}
          >
            <RefreshCw className="w-4 h-4" />
          </Button>

          <Button
            size="sm"
            startContent={<RefreshCw className={`w-3.5 h-3.5 ${syncMutation.isPending ? 'animate-spin' : ''}`} />}
            isLoading={syncMutation.isPending}
            isDisabled={!isGit}
            onPress={() => syncMutation.mutate()}
            className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
          >
            {t('git.oneClickSync')}
          </Button>
        </div>
      </div>

      {!isGit ? (
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-4">
          <div className="flex items-center gap-3 text-zinc-800 dark:text-zinc-200 font-semibold text-sm">
            <FolderGit2 className="w-5 h-5 text-zinc-500 dark:text-zinc-400" />
            <span>{t('git.notInitTitle')}</span>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {t('git.notInitDesc')}
          </p>
          <div className="flex items-center gap-3 pt-2">
            <Input
              size="sm"
              variant="bordered"
              value={syncDir}
              onValueChange={setSyncDir}
              placeholder={t('git.initPlaceholder')}
              className="max-w-md font-mono text-xs"
              classNames={{
                inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-9',
              }}
            />
            <Button
              size="sm"
              isLoading={initMutation.isPending}
              onPress={() => initMutation.mutate()}
              className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4"
            >
              {t('git.initRepo')}
            </Button>
          </div>
        </div>
      ) : (
        <>
          {/* Status Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex items-center justify-between">
              <div>
                <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">{t('git.activeBranch')}</div>
                <div className="text-base font-bold text-zinc-900 dark:text-white mt-1 font-mono flex items-center gap-1.5">
                  <GitBranch className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                  {gitStatus?.branch || 'main'}
                </div>
              </div>
              <div>
                {isClean ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40">
                    <CheckCircle2 className="w-3 h-3" /> {t('common.clean')}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/40">
                    <AlertCircle className="w-3 h-3" /> {t('git.changesPending', { count: totalPendingChanges })}
                  </span>
                )}
              </div>
            </div>

            <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex items-center justify-between">
              <div>
                <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">{t('git.syncDir')}</div>
                <div className="text-xs font-mono text-zinc-700 dark:text-zinc-300 mt-1 truncate max-w-[240px]" title={gitStatus?.sync_dir || gitStatus?.git_dir}>
                  {gitStatus?.sync_dir || gitStatus?.git_dir || '—'}
                </div>
              </div>
              <FolderGit2 className="w-5 h-5 text-zinc-400 dark:text-zinc-500" />
            </div>

            <div className="sm:col-span-2 p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-4">
                <div>
                  <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">{t('git.remoteTracking')}</div>
                  <div className="text-xs font-mono text-zinc-800 dark:text-zinc-200 mt-1 flex items-center gap-3">
                    <span className="flex items-center gap-1 text-zinc-700 dark:text-zinc-300 font-semibold">
                      <ArrowUp className="w-3.5 h-3.5 text-zinc-400" /> {t('git.ahead', { count: gitStatus?.ahead ?? 0 })}
                    </span>
                    <span className="flex items-center gap-1 text-zinc-700 dark:text-zinc-300 font-semibold">
                      <ArrowDown className="w-3.5 h-3.5 text-zinc-400" /> {t('git.behind', { count: gitStatus?.behind ?? 0 })}
                    </span>
                  </div>
                </div>

                <div className="h-8 w-px bg-zinc-200 dark:bg-white/[0.08] hidden md:block" />

                {/* Remote & Branch Inputs */}
                <div className="flex items-center gap-3">
                  <div className="w-36 sm:w-44">
                    <Input
                      size="sm"
                      variant="bordered"
                      label={t('git.remoteLabel')}
                      value={remoteName}
                      onValueChange={setRemoteName}
                      placeholder="origin"
                      className="font-mono text-xs"
                      classNames={{
                        inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-9 shadow-2xs',
                        label: 'text-[10px] text-zinc-500',
                      }}
                    />
                  </div>
                  <div className="w-48 sm:w-64">
                    <Input
                      size="sm"
                      variant="bordered"
                      label={t('git.branchLabel')}
                      value={remoteBranch}
                      onValueChange={setRemoteBranch}
                      placeholder="main"
                      className="font-mono text-xs"
                      classNames={{
                        inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-9 shadow-2xs',
                        label: 'text-[10px] text-zinc-500',
                      }}
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 self-end md:self-center">
                <Button
                  size="sm"
                  startContent={<ArrowDown className="w-3.5 h-3.5" />}
                  isLoading={pullMutation.isPending}
                  onPress={() => pullMutation.mutate(remoteBranch)}
                  className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-8 px-3.5"
                >
                  {t('git.pull')} ({remoteBranch})
                </Button>
                <Button
                  size="sm"
                  startContent={<ArrowUp className="w-3.5 h-3.5" />}
                  isLoading={pushMutation.isPending}
                  onPress={() => pushMutation.mutate(remoteBranch)}
                  className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-8 px-3.5"
                >
                  {t('git.push')} ({remoteBranch})
                </Button>
              </div>
            </div>
          </div>

          {/* Detailed Changes Inspector & Diff Viewer */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
                  <FileCode className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                  {t('git.inspectorTitle')}
                </h3>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {t('git.inspectorSubtitle')}
                </p>
              </div>

              {!isClean && (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    startContent={<Code2 className="w-3.5 h-3.5" />}
                    onPress={() => {
                      if (selectedDiffTarget?.type === 'all') {
                        setSelectedDiffTarget(null);
                      } else {
                        setSelectedDiffTarget({ type: 'all', label: t('git.viewFullDiff') });
                      }
                    }}
                    className={`text-xs font-medium rounded-full h-8 px-3.5 ${
                      selectedDiffTarget?.type === 'all'
                        ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                        : 'bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.08]'
                    }`}
                  >
                    {selectedDiffTarget?.type === 'all' ? t('git.hideDiff') : t('git.viewFullDiff')}
                  </Button>
                </div>
              )}
            </div>

            {isClean ? (
              <div className="flex items-center gap-2.5 p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 text-xs font-medium border border-emerald-200 dark:border-emerald-800/30">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span>{t('git.allInSync')}</span>
              </div>
            ) : (
              <div className="space-y-4">
                <Tabs
                  size="sm"
                  variant="underlined"
                  classNames={{
                    tabList: 'gap-6 w-full relative rounded-none p-0 border-b border-zinc-200 dark:border-white/[0.08]',
                    tab: 'max-w-fit px-0 h-10 text-xs font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 data-[selected=true]:text-zinc-900 dark:data-[selected=true]:text-white',
                    cursor: 'bg-zinc-900 dark:bg-white',
                    tabContent: 'text-zinc-500 group-data-[selected=true]:text-zinc-900 dark:text-zinc-400 dark:group-data-[selected=true]:text-white font-medium',
                  }}
                >
                  {/* Tab 1: Database Pending Export */}
                  <Tab
                    key="db-pending"
                    title={
                      <div className="flex items-center gap-1.5">
                        <Database className="w-3.5 h-3.5" />
                        <span>{t('git.dbPendingTab')}</span>
                        <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-zinc-100 dark:bg-white/10 text-zinc-600 dark:text-zinc-300">
                          {pendingExport.total}
                        </span>
                      </div>
                    }
                  >
                    <div className="pt-3 space-y-3">
                      {pendingExport.total === 0 ? (
                        <div className="text-xs text-zinc-500 italic py-2">
                          {t('git.dbAllExported')}
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          {/* Added */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 flex items-center justify-between">
                              <span className="flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> {t('git.addedInDb')}</span>
                              <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40">{pendingExport.added.length}</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {pendingExport.added.map((id) => (
                                <button
                                  key={id}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'doc', name: id, label: `DB Doc (New): ${id}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'doc' && selectedDiffTarget?.name === id
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={id}
                                >
                                  <span className="truncate">{id}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {pendingExport.added.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>

                          {/* Modified */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-amber-600 dark:text-amber-400 flex items-center justify-between">
                              <span className="flex items-center gap-1"><Edit3 className="w-3.5 h-3.5" /> {t('git.modifiedInDb')}</span>
                              <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/40">{pendingExport.modified.length}</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {pendingExport.modified.map((id) => (
                                <button
                                  key={id}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'doc', name: id, label: `DB Doc (Modified): ${id}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'doc' && selectedDiffTarget?.name === id
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={id}
                                >
                                  <span className="truncate">{id}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {pendingExport.modified.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>

                          {/* Deleted */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-red-600 dark:text-red-400 flex items-center justify-between">
                              <span className="flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" /> {t('git.deletedInDb')}</span>
                              <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800/40">{pendingExport.deleted.length}</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {pendingExport.deleted.map((id) => (
                                <button
                                  key={id}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'doc', name: id, label: `DB Doc (Deleted): ${id}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'doc' && selectedDiffTarget?.name === id
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={id}
                                >
                                  <span className="truncate">{id}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {pendingExport.deleted.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </Tab>

                  {/* Tab 2: Git Working Tree Files */}
                  <Tab
                    key="git-tree"
                    title={
                      <div className="flex items-center gap-1.5">
                        <FolderGit2 className="w-3.5 h-3.5" />
                        <span>{t('git.gitTreeTab')}</span>
                        <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-zinc-100 dark:bg-white/10 text-zinc-600 dark:text-zinc-300">
                          {staged.length + unstaged.length + untracked.length}
                        </span>
                      </div>
                    }
                  >
                    <div className="pt-3 space-y-3">
                      {staged.length === 0 && unstaged.length === 0 && untracked.length === 0 ? (
                        <div className="text-xs text-zinc-500 italic py-2">
                          {t('git.gitTreeClean')}
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          {/* Staged */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 flex items-center justify-between">
                              <span>{t('git.staged')} ({staged.length})</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {staged.map((item) => (
                                <button
                                  key={item.path}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'file', name: item.path, staged: true, label: `Staged: ${item.path}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'file' && selectedDiffTarget?.name === item.path && selectedDiffTarget?.staged
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={item.path}
                                >
                                  <span className="truncate">{item.status} {item.path}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {staged.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>

                          {/* Unstaged Modified */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-amber-600 dark:text-amber-400 flex items-center justify-between">
                              <span>{t('git.unstaged')} ({unstaged.length})</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {unstaged.map((item) => (
                                <button
                                  key={item.path}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'file', name: item.path, staged: false, label: `Modified: ${item.path}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'file' && selectedDiffTarget?.name === item.path && !selectedDiffTarget?.staged
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={item.path}
                                >
                                  <span className="truncate">{item.status} {item.path}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {unstaged.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>

                          {/* Untracked */}
                          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] space-y-2">
                            <div className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                              <span>{t('git.untracked')} ({untracked.length})</span>
                            </div>
                            <div className="space-y-1 max-h-36 overflow-y-auto">
                              {untracked.map((path) => (
                                <button
                                  key={path}
                                  type="button"
                                  onClick={() => setSelectedDiffTarget({ type: 'file', name: path, staged: false, label: `Untracked: ${path}` })}
                                  className={`w-full text-left px-2 py-1 rounded-lg text-xs font-mono truncate transition-colors flex items-center justify-between gap-1 ${
                                    selectedDiffTarget?.type === 'file' && selectedDiffTarget?.name === path
                                      ? 'bg-black dark:bg-white text-white dark:text-black font-semibold'
                                      : 'hover:bg-zinc-200/60 dark:hover:bg-white/[0.05] text-zinc-800 dark:text-zinc-300'
                                  }`}
                                  title={path}
                                >
                                  <span className="truncate">? {path}</span>
                                  <Eye className="w-3 h-3 shrink-0 opacity-60" />
                                </button>
                              ))}
                              {untracked.length === 0 && <span className="text-xs text-zinc-500 italic">{t('common.none')}</span>}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </Tab>
                </Tabs>

                {/* Diff Viewer Container */}
                {selectedDiffTarget && (
                  <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-white/[0.08] space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs font-semibold text-zinc-900 dark:text-white">
                        <Code2 className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                        <span>{t('git.diffPreview')}</span>
                        <span className="font-mono text-zinc-800 dark:text-zinc-200 bg-zinc-100 dark:bg-white/[0.05] border border-zinc-200 dark:border-white/[0.08] px-2 py-0.5 rounded-md">
                          {selectedDiffTarget.label || selectedDiffTarget.name || t('git.viewFullDiff')}
                        </span>
                      </div>
                      <Button
                        size="sm"
                        variant="light"
                        isIconOnly
                        onPress={() => setSelectedDiffTarget(null)}
                        className="text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-full w-7 h-7"
                        title={t('common.close')}
                      >
                        <EyeOff className="w-3.5 h-3.5" />
                      </Button>
                    </div>

                    {isDiffLoading ? (
                      <div className="flex items-center justify-center py-8">
                        <Spinner size="sm" label={t('git.loadingDiff')} />
                      </div>
                    ) : (
                      <div className="max-h-96 overflow-y-auto rounded-xl border border-zinc-200 dark:border-white/[0.08]">
                        <DiffViewer diffText={activeDiffText} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Commit Form */}
            <div className="pt-2 flex items-center gap-3">
              <Input
                size="sm"
                variant="bordered"
                value={commitMessage}
                onValueChange={setCommitMessage}
                placeholder={t('git.commitPlaceholder')}
                className="flex-1"
                classNames={{
                  inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-10 text-xs shadow-2xs',
                  input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
                }}
              />
              <Button
                size="sm"
                startContent={<GitCommit className="w-3.5 h-3.5" />}
                isLoading={commitMutation.isPending}
                onPress={() => commitMutation.mutate(commitMessage || 'admin commit')}
                className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-10 px-5 shadow-sm shrink-0"
              >
                {t('git.exportAndCommit')}
              </Button>
            </div>
          </div>

          {/* Commit History */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
            <h3 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
              <GitCommit className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              {t('git.recentCommits')}
            </h3>

            <div className="divide-y divide-zinc-100 dark:divide-white/[0.06] font-mono text-xs">
              {gitHistory?.commits && gitHistory.commits.length > 0 ? (
                gitHistory.commits.map((c) => (
                  <div key={c.hash} className="py-3 flex items-start justify-between gap-4">
                    <div className="space-y-1">
                      <div className="font-sans font-semibold text-zinc-800 dark:text-zinc-200 text-sm">
                        {c.message}
                      </div>
                      <div className="text-[11px] text-zinc-400 dark:text-zinc-500 font-sans">
                        {t('git.byAuthor', { author: c.author, date: c.date })}
                      </div>
                    </div>
                    <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-white/[0.04] text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-white/[0.08] font-bold shrink-0">
                      {c.hash.slice(0, 7)}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-xs text-zinc-500 py-4">{t('git.noCommits')}</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
