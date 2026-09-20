import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Input,
  Button,
  Checkbox,
  Spinner,
  Select,
  SelectItem,
} from '@heroui/react';
import {
  Search as SearchIcon,
  Sparkles,
  ChevronRight,
} from 'lucide-react';
import { api } from '../../api/client';
import { DocTypeInfo } from '../../types';
import { TypeBadge, TYPE_LABELS } from '../../components/Badge';

const DOC_TYPES = [
  'decision',
  'lesson',
  'project',
  'glossary',
  'api',
  'runbook',
  'release',
  'faq',
  'person',
];

export const SearchPage: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'hybrid' | 'lexical' | 'semantic' | 'fuzzy'>('hybrid');
  const [selectedType, setSelectedType] = useState('');
  const [expandGraph, setExpandGraph] = useState(true);
  const [limit] = useState(15);

  const isSearchActive = query.trim().length > 0;

  const { data, isLoading } = useQuery({
    queryKey: ['advanced-search', query, mode, selectedType, expandGraph, limit],
    queryFn: () =>
      api.search({
        q: query,
        mode,
        type: selectedType || undefined,
        limit,
        expand_graph: expandGraph,
      }),
    enabled: isSearchActive,
  });

  const { data: typesData } = useQuery<{ types: DocTypeInfo[] }>({
    queryKey: ['types'],
    queryFn: () => api.getTypes(),
  });

  const availableTypes = typesData?.types?.map((t) => ({
    name: t.name,
    label: t.label ? `${t.label} (${t.name})` : (TYPE_LABELS[t.name] || t.name),
  })) || DOC_TYPES.map((t) => ({
    name: t,
    label: TYPE_LABELS[t] || t,
  }));

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  const hits = data?.items || [];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
          <SearchIcon className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
          {t('search.title')}
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          {t('search.subtitle')}
        </p>
      </div>

      {/* Search Input & Controls (Grok Style Prompt Box) */}
      <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-4">
        <form onSubmit={handleSearchSubmit} className="flex gap-2">
          <Input
            isClearable
            onClear={() => setQuery('')}
            value={query}
            onValueChange={setQuery}
            placeholder={t('search.inputPlaceholder')}
            startContent={<SearchIcon className="w-4 h-4 text-zinc-400" />}
            size="md"
            variant="bordered"
            className="flex-1"
            classNames={{
              inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-11 text-xs shadow-2xs',
              input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
            }}
          />
          <Button
            type="submit"
            size="md"
            className="bg-black text-white hover:bg-zinc-800 dark:bg-white dark:text-black font-semibold text-xs rounded-full dark:hover:bg-zinc-200 h-11 px-5 shadow-sm shrink-0"
          >
            {t('common.search')}
          </Button>
        </form>

        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-3 border-t border-zinc-100 dark:border-white/[0.06] text-xs">
          {/* Mode Select */}
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">{t('search.scoring')}:</span>
            <div className="flex items-center p-0.5 rounded-full bg-zinc-100 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/[0.08]">
              {(['hybrid', 'lexical', 'semantic', 'fuzzy'] as const).map((m) => {
                const isActive = mode === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-all flex items-center gap-1 ${
                      isActive
                        ? 'bg-white text-zinc-900 dark:bg-white dark:text-black font-semibold shadow-xs'
                        : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'
                    }`}
                  >
                    {m === 'hybrid' && <Sparkles className="w-3 h-3" />}
                    {m}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="w-56">
              <Select
                size="sm"
                aria-label={t('types.typeName')}
                placeholder={t('documents.allTypes')}
                selectedKeys={selectedType ? [selectedType] : []}
                onChange={(e) => setSelectedType(e.target.value)}
                variant="bordered"
                disableAnimation
                classNames={{
                  trigger: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 text-xs rounded-xl min-h-8 shadow-2xs',
                  value: 'text-xs text-zinc-800 dark:text-zinc-300 font-medium',
                }}
              >
                {availableTypes.map((t) => (
                  <SelectItem key={t.name} textValue={t.label} className="text-xs">
                    {t.label}
                  </SelectItem>
                ))}
              </Select>
            </div>

            <Checkbox
              size="sm"
              isSelected={expandGraph}
              onValueChange={setExpandGraph}
              classNames={{ label: 'text-xs text-zinc-600 dark:text-zinc-400' }}
            >
              {t('search.expandGraph')}
            </Checkbox>
          </div>
        </div>
      </div>

      {/* Results Feed */}
      {isLoading ? (
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" label={t('common.loading')} />
        </div>
      ) : isSearchActive ? (
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs overflow-hidden divide-y divide-zinc-100 dark:divide-white/[0.06]">
          <div className="px-5 py-3 bg-zinc-50 dark:bg-white/[0.02] text-xs font-medium text-zinc-500 flex items-center justify-between">
            <span>{t('search.title')} ({hits.length})</span>
            <span className="font-mono text-[11px] text-zinc-500">{t('search.scoring')}: {mode}</span>
          </div>

          {hits.length > 0 ? (
            hits.map((hit, idx) => (
              <div
                key={hit.doc.id || idx}
                onClick={() => navigate(`/docs/${encodeURIComponent(hit.doc.id)}`)}
                className="p-5 hover:bg-zinc-50 dark:hover:bg-white/[0.03] cursor-pointer transition-colors space-y-2.5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <TypeBadge type={hit.doc.type} />
                      <h3 className="font-semibold text-base text-zinc-900 dark:text-zinc-100 hover:text-black dark:hover:text-white transition-colors">
                        {hit.doc.title}
                      </h3>
                      {hit.score !== undefined && (
                        <span className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-white/[0.04] text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08]">
                          {t('search.score')}: {hit.score.toFixed(3)}
                        </span>
                      )}
                      {hit.channel && (
                        <span className="font-mono text-[10px] px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-700 border border-zinc-200 dark:bg-zinc-900 dark:text-zinc-400 dark:border-zinc-800 uppercase">
                          {hit.channel}
                        </span>
                      )}
                    </div>

                    <div className="text-xs text-zinc-500 font-mono">
                      {hit.doc.id}
                    </div>

                    {hit.snippet ? (
                      <div
                        className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed font-sans bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.05] p-3 rounded-xl [&>mark]:bg-amber-500/20 [&>mark]:text-amber-800 dark:[&>mark]:text-amber-300 [&>mark]:font-medium [&>mark]:px-0.5"
                        dangerouslySetInnerHTML={{ __html: hit.snippet }}
                      />
                    ) : hit.doc.body ? (
                      <p className="text-xs text-zinc-600 dark:text-zinc-400 line-clamp-2 leading-relaxed font-sans">
                        {hit.doc.body}
                      </p>
                    ) : null}

                    {hit.neighbors && hit.neighbors.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-zinc-100 dark:border-white/[0.06] text-xs">
                        <span className="text-zinc-500 font-medium">{t('search.neighbors')}: </span>
                        <div className="inline-flex gap-2 flex-wrap pt-1">
                          {hit.neighbors.map((n: any, nIdx: number) => (
                            <span key={nIdx} className="font-mono text-[11px] px-2 py-0.5 rounded bg-zinc-100 text-zinc-700 border border-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-800">
                              {n.rel} → {n.to_id}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <ChevronRight className="w-4 h-4 text-zinc-400 shrink-0 mt-1" />
                </div>
              </div>
            ))
          ) : (
            <div className="p-16 text-center text-xs text-zinc-500">
              {t('search.noResults', { query })}
            </div>
          )}
        </div>
      ) : (
        <div className="p-16 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs text-center space-y-2">
          <Sparkles className="w-8 h-8 text-zinc-400 dark:text-zinc-600 mx-auto" />
          <h3 className="font-semibold text-sm text-zinc-800 dark:text-zinc-300">{t('search.startSearching')}</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">
            {t('search.startSearchingDesc')}
          </p>
        </div>
      )}
    </div>
  );
};
