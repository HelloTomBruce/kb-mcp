import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Input,
  Spinner,
  Select,
  SelectItem,
} from '@heroui/react';
import {
  Link2,
  Plus,
  Trash2,
  ExternalLink,
  Search,
  ArrowRight,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { LinkItem } from '../../types';
import { RELATION_LABELS } from '../../components/Badge';

const STANDARD_RELATIONS = [
  'relates-to',
  'depends-on',
  'supersedes',
  'superseded-by',
  'governs',
  'blocks',
  'implements',
  'references',
  'is_influence',
  'derives-from',
];

export const LinksPage: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [filterDocId, setFilterDocId] = useState('');
  const [filterRel, setFilterRel] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  // Form states
  const [fromId, setFromId] = useState('');
  const [toId, setToId] = useState('');
  const [rel, setRel] = useState('relates-to');

  const { data, isLoading } = useQuery({
    queryKey: ['links'],
    queryFn: () => api.getLinks(),
  });

  const { data: docsData } = useQuery({
    queryKey: ['docs-all-titles'],
    queryFn: () => api.getDocs(),
  });

  const docTitles = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const doc of docsData?.items || []) {
      if (doc.id && doc.title) {
        map.set(doc.id, doc.title);
      }
    }
    return map;
  }, [docsData]);

  const createMutation = useMutation({
    mutationFn: () => api.createLink({ from_id: fromId.trim(), to_id: toId.trim(), rel }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['links'] });
      setIsCreating(false);
      setFromId('');
      setToId('');
      toast.success(t('common.success'));
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (link: LinkItem) => api.deleteLink(link),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['links'] });
      toast.success(t('common.success'));
    },
    onError: (err: any) => toast.error(`${t('common.failed')}: ${err.message}`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label={t('common.loading')} />
      </div>
    );
  }

  const allLinks = data?.items || [];
  const filteredLinks = allLinks.filter((l) => {
    const fromTitle = docTitles.get(l.from_id) || '';
    const toTitle = docTitles.get(l.to_id) || '';
    const filterLower = filterDocId.toLowerCase();
    const matchDoc =
      !filterDocId ||
      l.from_id.toLowerCase().includes(filterLower) ||
      l.to_id.toLowerCase().includes(filterLower) ||
      fromTitle.toLowerCase().includes(filterLower) ||
      toTitle.toLowerCase().includes(filterLower);
    const matchRel = !filterRel || l.rel === filterRel;
    return matchDoc && matchRel;
  });

  const availableRels = Array.from(new Set(allLinks.map((l) => l.rel))).sort();

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <Link2 className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            {t('links.title')}
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            {t('links.subtitle')}
          </p>
        </div>

        <Button
          startContent={<Plus className="w-4 h-4" />}
          onPress={() => setIsCreating(true)}
          size="sm"
          className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
        >
          {t('links.createLink')}
        </Button>
      </div>

      {/* Filter and Create Section */}
      <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-3">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <Input
            size="sm"
            variant="bordered"
            isClearable
            onClear={() => setFilterDocId('')}
            value={filterDocId}
            onValueChange={setFilterDocId}
            placeholder={t('links.filterPlaceholder')}
            startContent={<Search className="w-4 h-4 text-zinc-400" />}
            className="flex-1 font-mono text-xs"
            classNames={{
              inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-9 text-xs shadow-2xs',
              input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
            }}
          />

          <div className="w-48">
            <Select
              size="sm"
              aria-label="Filter by relation"
              placeholder="All Relations"
              selectedKeys={filterRel ? [filterRel] : []}
              onChange={(e) => setFilterRel(e.target.value)}
              variant="bordered"
              disableAnimation
              classNames={{
                trigger: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 text-xs rounded-xl min-h-9 shadow-2xs',
                value: 'text-xs text-zinc-800 dark:text-zinc-300 font-mono',
              }}
            >
              {availableRels.map((r) => (
                <SelectItem key={r} textValue={r} className="text-xs font-mono">
                  {r}
                </SelectItem>
              ))}
            </Select>
          </div>
        </div>

              {/* Inline Create Box */}
        {isCreating && (
          <div className="mt-3 p-4 bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.08] rounded-xl space-y-3">
            <div className="flex items-center justify-between text-xs font-semibold text-zinc-900 dark:text-white">
              <span className="flex items-center gap-1.5"><Plus className="w-3.5 h-3.5" /> {t('links.addRelationEdge')}</span>
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="text-zinc-400 hover:text-zinc-800 dark:hover:text-white p-1 rounded-full"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Input
                size="sm"
                variant="bordered"
                label={t('links.sourceIdLabel')}
                placeholder={t('links.sourceIdPlaceholder')}
                value={fromId}
                onValueChange={setFromId}
                className="font-mono text-xs"
                classNames={{
                  inputWrapper: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl shadow-2xs',
                  label: 'text-[10px] text-zinc-500',
                  input: 'text-zinc-900 dark:text-zinc-100',
                }}
              />

              <div>
                <Select
                  size="sm"
                  label={t('links.relationVerb')}
                  selectedKeys={[rel]}
                  onChange={(e) => setRel(e.target.value || 'relates-to')}
                  variant="bordered"
                  disableAnimation
                  classNames={{
                    trigger: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-9 shadow-2xs',
                    label: 'text-[10px] text-zinc-500',
                    value: 'text-xs text-zinc-800 dark:text-zinc-200 font-medium',
                  }}
                >
                  {STANDARD_RELATIONS.map((r) => {
                    const info = RELATION_LABELS[r];
                    const label = info?.label || r;
                    const desc = info?.desc || '';
                    return (
                      <SelectItem
                        key={r}
                        textValue={label}
                        description={desc}
                        className="text-xs"
                      >
                        <div className="font-medium text-zinc-800 dark:text-zinc-200">{label}</div>
                      </SelectItem>
                    );
                  })}
                </Select>
              </div>

              <Input
                size="sm"
                variant="bordered"
                label={t('links.targetIdLabel')}
                placeholder={t('links.targetIdPlaceholder')}
                value={toId}
                onValueChange={setToId}
                className="font-mono text-xs"
                classNames={{
                  inputWrapper: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl shadow-2xs',
                  label: 'text-[10px] text-zinc-500',
                  input: 'text-zinc-900 dark:text-zinc-100',
                }}
              />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <Button
                size="sm"
                variant="light"
                onPress={() => setIsCreating(false)}
                className="text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white rounded-full text-xs"
              >
                {t('common.cancel')}
              </Button>
              <Button
                size="sm"
                isLoading={createMutation.isPending}
                isDisabled={!fromId.trim() || !toId.trim()}
                onPress={() => createMutation.mutate()}
                className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 px-4"
              >
                {t('links.createEdgeButton')}
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Table Container */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs overflow-hidden">
        <div className="px-5 py-3 bg-zinc-50 dark:bg-white/[0.02] text-xs font-medium text-zinc-500 flex items-center justify-between">
          <span>{t('links.edgesCount', { count: filteredLinks.length })}</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-white/[0.08] text-zinc-500 text-left bg-zinc-50 dark:bg-white/[0.02]">
                <th className="p-4 font-medium uppercase text-[11px]">{t('links.sourceCol')}</th>
                <th className="p-4 font-medium uppercase text-[11px]">{t('links.relationCol')}</th>
                <th className="p-4 font-medium uppercase text-[11px]">{t('links.targetCol')}</th>
                <th className="p-4 font-medium uppercase text-[11px] text-right">{t('links.actionsCol')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.04]">
              {filteredLinks.length > 0 ? (
                filteredLinks.map((link, idx) => {
                  const fromTitle = docTitles.get(link.from_id);
                  const toTitle = docTitles.get(link.to_id);
                  const relInfo = RELATION_LABELS[link.rel];
                  const relLabel = relInfo?.label || link.rel;
                  return (
                    <tr key={idx} className="hover:bg-zinc-50 dark:hover:bg-white/[0.02] transition-colors">
                      {/* From */}
                      <td className="p-4 align-middle">
                        <RouterLink
                          to={`/docs/${encodeURIComponent(link.from_id)}`}
                          className="group block space-y-0.5"
                        >
                          <div className="font-sans font-semibold text-zinc-900 dark:text-zinc-100 hover:text-black dark:hover:text-white flex items-center gap-1.5 transition-colors">
                            <span className="truncate max-w-sm">{fromTitle || link.from_id}</span>
                            <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-zinc-400 shrink-0" />
                          </div>
                          {fromTitle && (
                            <div className="text-[11px] font-mono text-zinc-400 dark:text-zinc-500 truncate max-w-sm">
                              {link.from_id}
                            </div>
                          )}
                        </RouterLink>
                      </td>

                      {/* Rel */}
                      <td className="p-4 align-middle">
                        <span
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-sans font-medium bg-zinc-100 dark:bg-white/[0.04] text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08]"
                          title={relInfo?.desc || link.rel}
                        >
                          <ArrowRight className="w-3 h-3 text-zinc-400 dark:text-zinc-500 shrink-0" />
                          <span>{relLabel}</span>
                        </span>
                      </td>

                      {/* To */}
                      <td className="p-4 align-middle">
                        <RouterLink
                          to={`/docs/${encodeURIComponent(link.to_id)}`}
                          className="group block space-y-0.5"
                        >
                          <div className="font-sans font-semibold text-zinc-900 dark:text-zinc-100 hover:text-black dark:hover:text-white flex items-center gap-1.5 transition-colors">
                            <span className="truncate max-w-sm">{toTitle || link.to_id}</span>
                            <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-zinc-400 shrink-0" />
                          </div>
                          {toTitle && (
                            <div className="text-[11px] font-mono text-zinc-400 dark:text-zinc-500 truncate max-w-sm">
                              {link.to_id}
                            </div>
                          )}
                        </RouterLink>
                      </td>

                      {/* Actions */}
                      <td className="p-4 text-right align-middle">
                        <Button
                          isIconOnly
                          size="sm"
                          variant="light"
                          isLoading={deleteMutation.isPending && (deleteMutation.variables as any) === link}
                          onPress={() => deleteMutation.mutate(link)}
                          className="text-zinc-400 hover:text-red-500 rounded-full w-7 h-7"
                          title={t('links.deleteLink')}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={4} className="p-12 text-center text-xs text-zinc-500 font-sans">
                    {t('links.noLinks')}
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
