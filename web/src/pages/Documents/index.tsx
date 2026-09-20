import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Input,
  Button,
  Checkbox,
  Spinner,
  Select,
  SelectItem,
} from '@heroui/react';
import {
  Search,
  Plus,
  Sparkles,
  ChevronRight,
  Copy,
  Check,
} from 'lucide-react';
import { api } from '../../api/client';
import { DocumentItem, DocTypeInfo } from '../../types';
import { TypeBadge, TagBadge, TYPE_LABELS } from '../../components/Badge';

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

export const DocumentsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const queryText = searchParams.get('q') || '';
  const activeType = searchParams.get('type') || '';
  const activeTag = searchParams.get('tag') || '';
  const [searchMode, setSearchMode] = useState<'hybrid' | 'lexical' | 'semantic' | 'fuzzy'>('hybrid');
  const [expandGraph, setExpandGraph] = useState(false);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const updateFilters = (newQ?: string, newType?: string, newTag?: string) => {
    const params = new URLSearchParams(searchParams);
    if (newQ !== undefined) {
      if (newQ) params.set('q', newQ);
      else params.delete('q');
    }
    if (newType !== undefined) {
      if (newType) params.set('type', newType);
      else params.delete('type');
    }
    if (newTag !== undefined) {
      if (newTag) params.set('tag', newTag);
      else params.delete('tag');
    }
    setSearchParams(params, { replace: true });
  };

  const isSearchActive = queryText.trim().length > 0;

  const { data: searchResults, isLoading: isSearchLoading } = useQuery({
    queryKey: ['search', queryText, searchMode, activeType, expandGraph],
    queryFn: () =>
      api.search({
        q: queryText,
        mode: searchMode,
        type: activeType || undefined,
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

  const { data: listResults, isLoading: isListLoading } = useQuery({
    queryKey: ['docs', activeType, activeTag, includeDeleted],
    queryFn: () =>
      api.getDocs({
        type: activeType || undefined,
        tag: activeTag || undefined,
        include_deleted: includeDeleted,
      }),
    enabled: !isSearchActive,
  });

  const handleCopy = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const isLoading = isSearchActive ? isSearchLoading : isListLoading;

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">Documents</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Browse, search, and manage your agent knowledge records
          </p>
        </div>

        <Button
          startContent={<Plus className="w-4 h-4" />}
          onPress={() => navigate('/docs/new')}
          size="sm"
          className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
        >
          Create Document
        </Button>
      </div>

      {/* Search & Filter Bar */}
      <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs space-y-4">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3">
          <Input
            isClearable
            onClear={() => updateFilters('', undefined, undefined)}
            value={queryText}
            onValueChange={(val) => updateFilters(val, undefined, undefined)}
            placeholder="Search knowledge by keyword, meaning or ID..."
            startContent={<Search className="w-4 h-4 text-zinc-400" />}
            size="sm"
            variant="bordered"
            className="flex-1"
            classNames={{
              inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-10 text-xs shadow-2xs',
              input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
            }}
          />

          {/* Grok-style Pill Mode Selectors */}
          <div className="flex items-center p-1 rounded-full bg-zinc-100 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/[0.08] shrink-0">
            {(['hybrid', 'lexical', 'semantic', 'fuzzy'] as const).map((mode) => {
              const isActive = searchMode === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setSearchMode(mode)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium capitalize transition-all flex items-center gap-1 ${
                    isActive
                      ? 'bg-white dark:bg-white text-black dark:text-black font-semibold shadow-xs'
                      : 'text-zinc-600 dark:text-zinc-400 hover:text-black dark:hover:text-zinc-100'
                  }`}
                >
                  {mode === 'hybrid' && <Sparkles className="w-3 h-3" />}
                  {mode}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-zinc-100 dark:border-white/[0.06] text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-56">
              <Select
                size="sm"
                aria-label="Filter by Type"
                placeholder="All Types"
                selectedKeys={activeType ? [activeType] : []}
                onChange={(e) => updateFilters(undefined, e.target.value, undefined)}
                variant="bordered"
                disableAnimation
                className="max-w-xs"
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

            {activeTag && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono bg-zinc-100 dark:bg-white/10 text-zinc-800 dark:text-white border border-zinc-200 dark:border-white/20">
                #{activeTag}
                <button
                  type="button"
                  onClick={() => updateFilters(undefined, undefined, '')}
                  className="hover:text-red-500 ml-1"
                >
                  ×
                </button>
              </span>
            )}
          </div>

          <div className="flex items-center gap-4">
            {isSearchActive && (
              <Checkbox
                size="sm"
                isSelected={expandGraph}
                onValueChange={setExpandGraph}
                classNames={{ label: 'text-xs text-zinc-600 dark:text-zinc-400' }}
              >
                Expand Graph (+1 hop)
              </Checkbox>
            )}

            <Checkbox
              size="sm"
              isSelected={includeDeleted}
              onValueChange={setIncludeDeleted}
              classNames={{ label: 'text-xs text-zinc-600 dark:text-zinc-400' }}
            >
              Include Deleted
            </Checkbox>
          </div>
        </div>
      </div>

      {/* Results List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" label="Searching documents..." />
        </div>
      ) : (
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] overflow-hidden divide-y divide-zinc-100 dark:divide-white/[0.06] shadow-xs">
          <div className="px-5 py-3 bg-zinc-50/50 dark:bg-white/[0.02] text-xs font-medium text-zinc-500 flex items-center justify-between">
            <span>
              {isSearchActive
                ? `Search Hits: ${searchResults?.items.length ?? 0}`
                : `Total Documents: ${listResults?.items.length ?? 0}`}
            </span>
          </div>

          {isSearchActive ? (
            searchResults?.items && searchResults.items.length > 0 ? (
              searchResults.items.map((hit) => (
                <DocListItem
                  key={hit.doc.id}
                  doc={hit.doc}
                  score={hit.score}
                  channel={hit.channel}
                  neighbors={hit.neighbors}
                  onCopy={(e) => handleCopy(hit.doc.id, e)}
                  isCopied={copiedId === hit.doc.id}
                  onSelect={() => navigate(`/docs/${encodeURIComponent(hit.doc.id)}`)}
                />
              ))
            ) : (
              <div className="p-12 text-center text-xs text-zinc-500">No matching documents found.</div>
            )
          ) : listResults?.items && listResults.items.length > 0 ? (
            listResults.items.map((doc) => (
              <DocListItem
                key={doc.id}
                doc={doc}
                onCopy={(e) => handleCopy(doc.id, e)}
                isCopied={copiedId === doc.id}
                onSelect={() => navigate(`/docs/${encodeURIComponent(doc.id)}`)}
              />
            ))
          ) : (
            <div className="p-12 text-center text-xs text-zinc-500">No documents found.</div>
          )}
        </div>
      )}
    </div>
  );
};

interface DocListItemProps {
  doc: DocumentItem;
  score?: number;
  channel?: string;
  neighbors?: any[];
  onCopy: (e: React.MouseEvent) => void;
  isCopied: boolean;
  onSelect: () => void;
}

const DocListItem: React.FC<DocListItemProps> = ({
  doc,
  score,
  channel,
  neighbors,
  onCopy,
  isCopied,
  onSelect,
}) => {
  return (
    <div
      onClick={onSelect}
      className={`p-5 hover:bg-zinc-50 dark:hover:bg-white/[0.03] cursor-pointer transition-colors ${
        doc.deleted_at ? 'opacity-60 bg-red-50 dark:bg-red-950/10' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2 flex-1 min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <TypeBadge type={doc.type} />
            <h3 className="font-semibold text-base text-zinc-800 dark:text-zinc-100 hover:text-black dark:hover:text-white transition-colors">
              {doc.title}
            </h3>
            {doc.deleted_at && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800/40">
                Deleted
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 text-xs text-zinc-400 dark:text-zinc-500 font-mono">
            <span className="bg-zinc-100 dark:bg-white/[0.04] border border-zinc-200 dark:border-white/[0.08] px-2 py-0.5 rounded-md flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
              {doc.id}
              <button
                type="button"
                onClick={onCopy}
                title="Copy ID"
                className="hover:text-black dark:hover:text-white p-0.5"
              >
                {isCopied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
              </button>
            </span>

            {score !== undefined && (
              <span className="px-2 py-0.5 rounded-md text-[10px] font-mono bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700">
                Score: {score.toFixed(3)} ({channel})
              </span>
            )}

            {doc.source && (
              <span className="text-zinc-400 dark:text-zinc-500 font-sans truncate max-w-xs">
                from: {doc.source}
              </span>
            )}
          </div>

          {doc.body && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 leading-relaxed font-sans">
              {doc.body}
            </p>
          )}

          {doc.tags && doc.tags.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap pt-1">
              {doc.tags.map((tag) => (
                <TagBadge key={tag} tag={tag} />
              ))}
            </div>
          )}

          {neighbors && neighbors.length > 0 && (
            <div className="mt-2 pt-2 border-t border-zinc-100 dark:border-white/[0.06] text-xs">
              <span className="text-zinc-400 dark:text-zinc-500 font-medium">1-hop Neighbors: </span>
              <div className="inline-flex gap-2 flex-wrap">
                {neighbors.map((n, idx) => (
                  <span key={idx} className="font-mono text-[11px] px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-800">
                    {n.rel} → {n.to_id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0 text-xs text-zinc-400 dark:text-zinc-500 font-mono">
          <span>{doc.created_at ? doc.created_at.split('T')[0] : ''}</span>
          <ChevronRight className="w-4 h-4 text-zinc-400 dark:text-zinc-600" />
        </div>
      </div>
    </div>
  );
};
