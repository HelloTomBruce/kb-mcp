import React from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  Button,
  Switch,
  Spinner,
} from '@heroui/react';
import {
  Clock,
  Play,
  History,
  RotateCw,
  Activity,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';

export const SchedulerPage: React.FC = () => {
  const { isLoading: isStatusLoading } = useQuery({
    queryKey: ['scheduler-status'],
    queryFn: () => api.getSchedulerStatus(),
  });

  const { data: tasksData, isLoading: isTasksLoading, refetch: refetchTasks } = useQuery({
    queryKey: ['scheduler-tasks'],
    queryFn: () => api.getSchedulerTasks(),
  });

  const { data: historyData, isLoading: isHistoryLoading, refetch: refetchHistory } = useQuery({
    queryKey: ['scheduler-history'],
    queryFn: () => api.getSchedulerHistory(50),
  });

  const runMutation = useMutation({
    mutationFn: (taskName: string) => api.runSchedulerTask(taskName),
    onSuccess: (data) => {
      refetchTasks();
      refetchHistory();
      if (data.status === 'ok') {
        toast.success(`Task [${data.task_name}] executed (${data.duration_ms}ms)`);
      } else {
        toast.error(`Task [${data.task_name}] failed: ${data.error || 'Unknown error'}`);
      }
    },
    onError: (err: any) => toast.error(`Task run failed: ${err.message}`),
  });

  const toggleMutation = useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) => {
      if (enabled) {
        return api.disableSchedulerTask(name);
      } else {
        return api.enableSchedulerTask(name);
      }
    },
    onSuccess: () => {
      refetchTasks();
      toast.success('Task schedule state updated.');
    },
    onError: (err: any) => toast.error(`Toggle failed: ${err.message}`),
  });

  const isLoading = isStatusLoading || isTasksLoading || isHistoryLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label="Loading scheduler tasks..." />
      </div>
    );
  }

  const tasksList = tasksData?.tasks || [];
  const historyList = historyData?.history || [];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <Clock className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            Background Task Scheduler
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Manage autonomous knowledge maintenance, automatic git sync, vector embeddings, and integrity self-healing
          </p>
        </div>

        <Button
          size="sm"
          startContent={<RotateCw className="w-3.5 h-3.5" />}
          onPress={() => {
            refetchTasks();
            refetchHistory();
          }}
          className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
        >
          Refresh
        </Button>
      </div>

      {/* Engine Status Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex items-center justify-between">
          <div>
            <div className="text-[11px] text-zinc-500 uppercase font-medium">Scheduler Engine</div>
            <div className="text-base font-bold text-zinc-900 dark:text-white mt-1 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Running</span>
            </div>
          </div>
          <Activity className="w-5 h-5 text-zinc-400" />
        </div>

        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex items-center justify-between">
          <div>
            <div className="text-[11px] text-zinc-500 uppercase font-medium">Active Jobs</div>
            <div className="text-2xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">
              {tasksList.filter((t) => t.enabled).length} / {tasksList.length}
            </div>
          </div>
          <Clock className="w-5 h-5 text-zinc-400" />
        </div>

        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs flex items-center justify-between">
          <div>
            <div className="text-[11px] text-zinc-500 uppercase font-medium">Recorded Executions</div>
            <div className="text-2xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">
              {historyList.length}
            </div>
          </div>
          <History className="w-5 h-5 text-zinc-400" />
        </div>
      </div>

      {/* Configured Scheduled Tasks */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
        <h2 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
          <Clock className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
          Scheduled Maintenance Tasks
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-white/[0.08] text-zinc-500 text-left bg-zinc-50 dark:bg-white/[0.02]">
                <th className="p-3.5 font-medium uppercase text-[11px]">STATUS</th>
                <th className="p-3.5 font-medium uppercase text-[11px]">TASK</th>
                <th className="p-3.5 font-medium uppercase text-[11px]">CADENCE</th>
                <th className="p-3.5 font-medium uppercase text-[11px]">LAST RUN</th>
                <th className="p-3.5 font-medium uppercase text-[11px]">NEXT RUN</th>
                <th className="p-3.5 font-medium uppercase text-[11px] text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.04]">
              {tasksList.map((task) => (
                <tr key={task.name} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02] transition-colors">
                  <td className="p-3.5">
                    <Switch
                      size="sm"
                      isSelected={task.enabled}
                      onValueChange={() =>
                        toggleMutation.mutate({ name: task.name, enabled: task.enabled })
                      }
                      color="default"
                    />
                  </td>
                  <td className="p-3.5">
                    <div className="font-semibold text-zinc-900 dark:text-zinc-100 font-mono text-sm">
                      {task.name}
                    </div>
                    {task.description && (
                      <div className="text-[11px] text-zinc-500 mt-0.5 max-w-sm">
                        {task.description}
                      </div>
                    )}
                  </td>
                  <td className="p-3.5 font-mono text-zinc-700 dark:text-zinc-300">
                    {task.cron || (task.interval_seconds ? `${task.interval_seconds}s` : 'Manual')}
                  </td>
                  <td className="p-3.5">
                    {task.last_run ? (
                      <div className="space-y-0.5">
                        <div className="text-zinc-800 dark:text-zinc-300 font-mono">{task.last_run.split('T')[0]} {task.last_run.split('T')[1]?.slice(0, 8)}</div>
                        <div className="flex items-center gap-1.5 text-[10px]">
                          {task.last_status === 'ok' ? (
                            <span className="text-emerald-600 dark:text-emerald-400">Success</span>
                          ) : (
                            <span className="text-red-600 dark:text-red-400">Failed</span>
                          )}
                          {task.last_duration_ms !== undefined && (
                            <span className="text-zinc-500">({task.last_duration_ms}ms)</span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <span className="text-zinc-500 font-mono text-xs">Never</span>
                    )}
                  </td>
                  <td className="p-3.5 text-zinc-500 dark:text-zinc-400 font-mono">
                    {task.next_run ? task.next_run.split('T')[1]?.slice(0, 8) : '—'}
                  </td>
                  <td className="p-3.5 text-right">
                    <Button
                      size="sm"
                      startContent={<Play className="w-3 h-3" />}
                      isLoading={runMutation.isPending && runMutation.variables === task.name}
                      onPress={() => runMutation.mutate(task.name)}
                      className="bg-zinc-100 hover:bg-zinc-200 text-zinc-800 border-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] dark:text-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-7 px-3"
                    >
                      Run Now
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Task Execution History */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
        <h2 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
          <History className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
          Execution Log
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-white/[0.08] text-zinc-500 text-left">
                <th className="pb-3 font-medium uppercase text-[11px]">Time</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Task Name</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Status</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Duration</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Error/Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.04]">
              {historyList.length > 0 ? (
                historyList.map((item, idx) => (
                  <tr key={idx} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 text-zinc-500 pr-4">{item.timestamp || item.created_at}</td>
                    <td className="py-3 font-semibold text-zinc-800 dark:text-zinc-200 pr-4">{item.task_name}</td>
                    <td className="py-3 pr-4">
                      {item.status === 'ok' ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/40">
                          OK
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] bg-red-100 text-red-800 border border-red-300 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800/40">
                          FAIL
                        </span>
                      )}
                    </td>
                    <td className="py-3 text-zinc-500 dark:text-zinc-400 pr-4">{item.duration_ms}ms</td>
                    <td className="py-3 text-red-500 dark:text-red-400 truncate max-w-xs">{item.error || '—'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-zinc-500">
                    No execution logs recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
