import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Button,
  Spinner,
} from '@heroui/react';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  Database,
  Wrench,
  Clock,
  ShieldCheck,
  FileCode,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';

export const HealthPage: React.FC = () => {
  const { data: healthData, isLoading, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.getHealth(),
  });

  const { data: auditData } = useQuery({
    queryKey: ['audit'],
    queryFn: () => api.getAudit(50),
  });

  const handleFixDoctor = async () => {
    try {
      await api.fixDoctor();
      refetch();
      toast.success('Knowledge integrity check & auto-repair completed.');
    } catch (err: any) {
      toast.error(`Auto-repair failed: ${err.message}`);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label="Running health diagnostic checks..." />
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <Activity className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            System Health & Audit
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Knowledge integrity diagnostics, schema versioning, and operation audit trail
          </p>
        </div>

        <Button
          size="sm"
          startContent={<Wrench className="w-3.5 h-3.5" />}
          onPress={handleFixDoctor}
          className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
        >
          Run Doctor Auto-Repair
        </Button>
      </div>

      {/* Database & Schema Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-2">
          <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5" /> Database Path
          </div>
          <div className="text-xs font-mono text-zinc-700 dark:text-zinc-300 break-all bg-zinc-50 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/[0.06] p-2.5 rounded-xl">
            {healthData?.db_path}
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-2">
          <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
            <FileCode className="w-3.5 h-3.5" /> Schema Version
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            v{healthData?.schema_version}
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-2">
          <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" /> Doctor Status
          </div>
          <div className="text-base font-bold flex items-center gap-2 mt-1">
            {healthData?.ok ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/40">
                <CheckCircle2 className="w-3.5 h-3.5" /> All Checks Passed
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 border border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/40">
                <AlertTriangle className="w-3.5 h-3.5" /> Issues Detected
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Doctor Checks List */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
        <h2 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
          Integrity Checks
        </h2>
        <div className="divide-y divide-zinc-100 dark:divide-white/[0.06]">
          {healthData?.checks && healthData.checks.length > 0 ? (
            healthData.checks.map((check: any, idx: number) => (
              <div key={idx} className="py-3.5 flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {check.ok ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0" />
                    )}
                    <span className="font-semibold text-sm text-zinc-800 dark:text-zinc-200">
                      {check.name}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 pl-6">{check.detail}</p>
                </div>
                {check.auto_fixable && (
                  <span className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-700 border border-zinc-200 dark:bg-white/[0.04] dark:text-zinc-300 dark:border-white/[0.08] shrink-0">
                    Auto-fixable
                  </span>
                )}
              </div>
            ))
          ) : (
            <div className="text-xs text-zinc-500 py-4">No check results available.</div>
          )}
        </div>
      </div>

      {/* Audit Log */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
        <h2 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
          <Clock className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
          Recent Audit Log
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-white/[0.08] text-zinc-500 text-left">
                <th className="pb-3 font-medium uppercase text-[11px]">Timestamp</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Action</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Target</th>
                <th className="pb-3 font-medium uppercase text-[11px]">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.04]">
              {auditData?.items && auditData.items.length > 0 ? (
                auditData.items.map((log: any, idx: number) => (
                  <tr key={idx} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 text-zinc-500 whitespace-nowrap pr-4">{log.timestamp || log.created_at}</td>
                    <td className="py-3 pr-4">
                      <span className="px-2 py-0.5 rounded bg-zinc-100 text-zinc-700 border border-zinc-200 dark:bg-white/[0.04] dark:text-zinc-300 dark:border-white/[0.06]">
                        {log.action}
                      </span>
                    </td>
                    <td className="py-3 text-zinc-800 dark:text-zinc-300 font-semibold pr-4">{log.doc_id || log.target || '—'}</td>
                    <td className="py-3 text-zinc-500 dark:text-zinc-400 max-w-xs truncate">{log.details ? JSON.stringify(log.details) : '—'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-zinc-500">
                    No recent audit logs.
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
