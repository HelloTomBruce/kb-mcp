import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  Button,
  Spinner,
} from '@heroui/react';
import {
  FileText,
  Network,
  Cpu,
  CheckCircle2,
  AlertTriangle,
  ArrowUpRight,
  Sparkles,
  Clock,
  Layers,
  Tag as TagIcon,
  Wrench,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { TypeBadge, TagBadge } from '../../components/Badge';

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.getStats(),
  });

  const handleFixDoctor = async () => {
    try {
      await api.fixDoctor();
      refetch();
      toast.success('Knowledge base integrity auto-repair executed successfully.');
    } catch (err: any) {
      toast.error(`Auto-repair failed: ${err.message}`);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" label="Loading knowledge metrics..." />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6 rounded-2xl border border-red-500/20 bg-red-950/20 text-red-300">
        <h3 className="font-semibold text-base mb-1">Failed to load overview data</h3>
        <p className="text-xs text-red-400">{(error as Error)?.message || 'Unknown error occurred'}</p>
      </div>
    );
  }

  const stats = data?.stats || { docs: 0, links: 0 };
  const doctorReport = data?.doctor_report;
  const hasDoctorIssue = doctorReport && !doctorReport.ok;

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            Knowledge Overview
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Real-time status, semantic vectors, and graph topology analysis
          </p>
        </div>

        {hasDoctorIssue && (
          <Button
            startContent={<Wrench className="w-3.5 h-3.5" />}
            onPress={handleFixDoctor}
            size="sm"
            className="bg-amber-500 text-black font-semibold text-xs rounded-full hover:bg-amber-400 shadow-sm"
          >
            Auto-Repair Graph Issues
          </Button>
        )}
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Docs */}
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/[0.15] shadow-xs transition-all flex items-center justify-between">
          <div>
            <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">
              Documents
            </div>
            <div className="text-2xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">
              {stats.documents ?? stats.docs ?? 0}
            </div>
          </div>
          <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-white/[0.04] border border-zinc-200 dark:border-white/[0.08] text-zinc-600 dark:text-zinc-300 flex items-center justify-center">
            <FileText className="w-5 h-5" />
          </div>
        </div>

        {/* Total Links */}
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/[0.15] shadow-xs transition-all flex items-center justify-between">
          <div>
            <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">
              Relations (Links)
            </div>
            <div className="text-2xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">
              {stats.links ?? 0}
            </div>
          </div>
          <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-white/[0.04] border border-zinc-200 dark:border-white/[0.08] text-zinc-600 dark:text-zinc-300 flex items-center justify-center">
            <Network className="w-5 h-5" />
          </div>
        </div>

        {/* Semantic Embeddings */}
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/[0.15] shadow-xs transition-all flex items-center justify-between">
          <div>
            <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">
              Semantic Vectors
            </div>
            <div className="mt-1.5 flex items-center">
              {data?.embed_enabled ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40 font-mono">
                  <Sparkles className="w-3 h-3" />
                  Active {data.embed_dim && data.embed_dim > 0 ? `(${data.embed_dim}d)` : '(Ready)'}
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-zinc-100 dark:bg-zinc-900 text-zinc-500 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-800 font-mono">
                  FTS-only mode
                </span>
              )}
            </div>
          </div>
          <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-white/[0.04] border border-zinc-200 dark:border-white/[0.08] text-zinc-600 dark:text-zinc-300 flex items-center justify-center">
            <Sparkles className="w-5 h-5" />
          </div>
        </div>

        {/* Health / Doctor */}
        <div className="p-5 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/[0.15] shadow-xs transition-all flex items-center justify-between">
          <div>
            <div className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">
              Integrity Status
            </div>
            <div className="mt-1.5 flex items-center">
              {doctorReport?.ok ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40">
                  <CheckCircle2 className="w-3 h-3" />
                  Healthy
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/40">
                  <AlertTriangle className="w-3 h-3" />
                  Attention Needed
                </span>
              )}
            </div>
          </div>
          <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-white/[0.04] border border-zinc-200 dark:border-white/[0.08] text-zinc-600 dark:text-zinc-300 flex items-center justify-center">
            <Cpu className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Main Sections: Left (Recent Docs) & Right (Type/Tag Distribution) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Documents */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Recently Updated Documents
            </h2>
            <Button
              as={Link}
              to="/docs"
              size="sm"
              variant="light"
              endContent={<ArrowUpRight className="w-3.5 h-3.5" />}
              className="text-xs text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-full h-7 px-3"
            >
              View All
            </Button>
          </div>

          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] divide-y divide-zinc-100 dark:divide-white/[0.06] overflow-hidden shadow-xs">
            {data?.recent_docs && data.recent_docs.length > 0 ? (
              data.recent_docs.map((doc) => (
                <div
                  key={doc.id}
                  onClick={() => navigate(`/docs/${encodeURIComponent(doc.id)}`)}
                  className="p-4 hover:bg-zinc-50/80 dark:hover:bg-white/[0.03] cursor-pointer transition-colors flex items-start justify-between gap-4"
                >
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <TypeBadge type={doc.type} />
                      <span className="font-semibold text-sm text-zinc-800 dark:text-zinc-100 truncate">
                        {doc.title}
                      </span>
                    </div>
                    <div className="text-xs text-zinc-400 dark:text-zinc-500 font-mono truncate">
                      {doc.id}
                    </div>
                    {doc.tags && doc.tags.length > 0 && (
                      <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                        {doc.tags.map((t) => (
                          <TagBadge key={t} tag={t} />
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-zinc-400 dark:text-zinc-500 font-mono whitespace-nowrap shrink-0">
                    {doc.updated_at ? doc.updated_at.split('T')[0] : ''}
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-xs text-zinc-500">
                No documents found.
              </div>
            )}
          </div>
        </div>

        {/* Right Sidebar: Types & Tags */}
        <div className="space-y-6">
          {/* Document Types */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] p-5 space-y-3 shadow-xs">
            <div className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Document Types
            </div>
            <div className="space-y-1.5 pt-1">
              {data?.type_counts && data.type_counts.length > 0 ? (
                data.type_counts.map((tc) => (
                  <div
                    key={tc.type}
                    onClick={() => navigate(`/docs?type=${tc.type}`)}
                    className="flex items-center justify-between p-2 rounded-xl hover:bg-zinc-50 dark:hover:bg-white/[0.04] cursor-pointer transition-colors text-xs"
                  >
                    <TypeBadge type={tc.type} />
                    <span className="font-mono text-xs px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-white/[0.04] text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.06]">
                      {tc.count}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-xs text-zinc-500">No types recorded.</div>
              )}
            </div>
          </div>

          {/* Popular Tags */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] p-5 space-y-3 shadow-xs">
            <div className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
              <TagIcon className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Tags
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {data?.tag_counts && data.tag_counts.length > 0 ? (
                data.tag_counts.map((tc) => (
                  <button
                    key={tc.tag}
                    type="button"
                    onClick={() => navigate(`/docs?tag=${tc.tag}`)}
                    className="px-2.5 py-1 rounded-full text-xs font-mono bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.03] dark:hover:bg-white/[0.08] text-zinc-600 dark:text-zinc-400 hover:text-black dark:hover:text-zinc-200 border border-zinc-200 dark:border-white/[0.08] transition-all cursor-pointer"
                  >
                    #{tc.tag} <span className="text-zinc-400 dark:text-zinc-600">({tc.count})</span>
                  </button>
                ))
              ) : (
                <div className="text-xs text-zinc-500">No tags recorded.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
