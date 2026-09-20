import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Network as VisNetwork } from 'vis-network';
import {
  Input,
  Select,
  SelectItem,
  Button,
  Spinner,
} from '@heroui/react';
import {
  Network,
  Maximize2,
  ExternalLink,
  Search,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import { GraphNode } from '../../types';
import { TypeBadge, TagBadge, TYPE_LABELS } from '../../components/Badge';

export const GraphViewPage: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<VisNetwork | null>(null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [filterType, setFilterType] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const { data: graphData, isLoading: isGraphLoading } = useQuery({
    queryKey: ['graph'],
    queryFn: () => api.getGraph(),
  });

  const { data: typesData, isLoading: isTypesLoading } = useQuery({
    queryKey: ['types'],
    queryFn: () => api.getTypes(),
  });

  const typesList = typesData?.types || [];

  // Map type name to its configured color & label info
  const typeMap = React.useMemo(() => {
    const map = new Map<string, { label: string; color: string }>();
    typesList.forEach((t) => {
      map.set(t.name.toLowerCase(), {
        label: t.label || t.name,
        color: t.color || '#71717a',
      });
    });
    return map;
  }, [typesList]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    // Filter nodes if type selected
    const filteredNodes = filterType
      ? graphData.nodes.filter((n) => n.type.toLowerCase() === filterType.toLowerCase())
      : graphData.nodes;

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = graphData.edges.filter(
      (e) => nodeIds.has(e.from) && nodeIds.has(e.to)
    );

    const isDarkMode = document.documentElement.classList.contains('dark');

    const visNodes = filteredNodes.map((n) => {
      const typeInfo = typeMap.get(n.type.toLowerCase());
      const baseColor = typeInfo?.color || '#71717a';

      return {
        id: n.id,
        label: n.title || n.label || n.id,
        title: `${typeInfo?.label || n.type}: ${n.id}`,
        color: {
          background: baseColor,
          border: baseColor,
          highlight: {
            background: baseColor,
            border: isDarkMode ? '#ffffff' : '#000000',
          },
        },
        font: {
          color: isDarkMode ? '#e4e4e7' : '#18181b',
          size: 11,
          face: 'sans-serif',
        },
        shape: 'dot',
        size: 14,
        rawNode: n,
      };
    });

    const visEdges = filteredEdges.map((e) => ({
      from: e.from,
      to: e.to,
      label: e.rel || e.label || '',
      arrows: 'to',
      font: { size: 9, align: 'middle', color: isDarkMode ? '#71717a' : '#a1a1aa' },
      color: {
        color: isDarkMode ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)',
        highlight: isDarkMode ? '#ffffff' : '#000000',
      },
      smooth: { type: 'continuous' },
    }));

    const options = {
      nodes: {
        borderWidth: 1.5,
        shadow: true,
      },
      edges: {
        width: 1.2,
        shadow: false,
      },
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -35,
          centralGravity: 0.005,
          springLength: 100,
          springConstant: 0.18,
        },
        stabilization: { iterations: 120 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
      },
    };

    const network = new VisNetwork(
      containerRef.current,
      { nodes: visNodes as any, edges: visEdges as any },
      options as any
    );

    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const clickedId = params.nodes[0];
        const found = graphData.nodes.find((n) => n.id === clickedId);
        if (found) setSelectedNode(found);
      } else {
        setSelectedNode(null);
      }
    });

    networkRef.current = network;

    return () => {
      network.destroy();
    };
  }, [graphData, filterType, typeMap]);

  const handleSearchNode = (query: string) => {
    setSearchQuery(query);
    if (!query || !networkRef.current || !graphData) return;

    const matched = graphData.nodes.find(
      (n) =>
        n.id.toLowerCase().includes(query.toLowerCase()) ||
        (n.title && n.title.toLowerCase().includes(query.toLowerCase()))
    );

    if (matched) {
      networkRef.current.focus(matched.id, {
        scale: 1.2,
        animation: { duration: 800, easingFunction: 'easeInOutQuad' },
      });
      setSelectedNode(matched);
    }
  };

  const handleFit = () => {
    if (networkRef.current) {
      networkRef.current.fit({
        animation: { duration: 600, easingFunction: 'easeInOutQuad' },
      });
    }
  };

  if (isGraphLoading || isTypesLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label={t('graph.rendering')} />
      </div>
    );
  }

  const allTypes = Array.from(new Set((graphData?.nodes || []).map((n) => n.type))).sort();

  return (
    <div className="space-y-4 max-w-7xl mx-auto flex flex-col h-[calc(100vh-6rem)]">
      {/* Top Controls Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <Network className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            {t('graph.title')}
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            {t('graph.subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Input
            size="sm"
            variant="bordered"
            isClearable
            onClear={() => handleSearchNode('')}
            value={searchQuery}
            onValueChange={handleSearchNode}
            placeholder={t('graph.focusNodePlaceholder')}
            startContent={<Search className="w-3.5 h-3.5 text-zinc-400" />}
            className="w-48 font-mono text-xs"
            classNames={{
              inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-8 text-xs shadow-2xs',
              input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
            }}
          />

          <div className="w-44">
            <Select
              size="sm"
              aria-label="Filter Type"
              placeholder={t('graph.allTypes')}
              selectedKeys={filterType ? [filterType] : []}
              onChange={(e) => setFilterType(e.target.value)}
              variant="bordered"
              disableAnimation
              classNames={{
                trigger: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 text-xs rounded-xl min-h-8 shadow-2xs',
                value: 'text-xs text-zinc-800 dark:text-zinc-300 font-medium',
              }}
            >
              {allTypes.map((tName) => {
                const info = typeMap.get(tName.toLowerCase());
                const localizedLabel = t(`typeNames.${tName.toLowerCase()}`, { defaultValue: info?.label || TYPE_LABELS[tName] || tName });
                return (
                  <SelectItem key={tName} textValue={localizedLabel} className="text-xs">
                    {localizedLabel}
                  </SelectItem>
                );
              })}
            </Select>
          </div>

          <Button
            size="sm"
            isIconOnly
            onPress={handleFit}
            className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.08] rounded-full w-8 h-8"
            title={t('graph.fitView')}
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {/* Main Graph Canvas Area */}
      <div className="flex-1 relative rounded-2xl bg-zinc-50 dark:bg-[#070709] border border-zinc-200 dark:border-white/[0.08] shadow-xs overflow-hidden">
        <div ref={containerRef} className="w-full h-full" />

        {/* Legend Overlay */}
        <div className="absolute top-4 left-4 p-3 bg-white/90 dark:bg-black/80 backdrop-blur-md rounded-xl border border-zinc-200 dark:border-white/[0.08] text-[11px] space-y-2 pointer-events-none max-h-[calc(100%-2rem)] overflow-y-auto shadow-sm">
          <div className="font-semibold text-zinc-500 dark:text-zinc-400 text-[10px] uppercase tracking-wider">
            {t('graph.legendTitle')}
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {typesList.map((tItem) => {
              const localizedLabel = t(`typeNames.${tItem.name.toLowerCase()}`, { defaultValue: tItem.label || tItem.name });
              return (
                <div key={tItem.name} className="flex items-center gap-1.5">
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0 border border-zinc-300 dark:border-white/20"
                    style={{ backgroundColor: tItem.color || '#71717a' }}
                  />
                  <span className="text-zinc-700 dark:text-zinc-300 truncate max-w-[100px]">{localizedLabel}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Selected Node Details Drawer */}
        {selectedNode && (
          <div className="absolute top-4 right-4 w-80 p-5 bg-white/95 dark:bg-[#0e0e12]/95 backdrop-blur-xl rounded-2xl border border-zinc-200 dark:border-white/[0.12] shadow-2xl space-y-4 animate-in fade-in slide-in-from-right-4 duration-200">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-1 min-w-0">
                <TypeBadge type={selectedNode.type} />
                <h3 className="font-bold text-sm text-zinc-900 dark:text-white pt-1 truncate">
                  {selectedNode.title || selectedNode.id}
                </h3>
                <div className="text-[11px] font-mono text-zinc-400 dark:text-zinc-500 truncate">
                  {selectedNode.id}
                </div>
              </div>

              <button
                type="button"
                onClick={() => setSelectedNode(null)}
                className="text-zinc-400 hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-white p-1 rounded-full"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {selectedNode.tags && selectedNode.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {selectedNode.tags.map((tTag) => (
                  <TagBadge key={tTag} tag={tTag} />
                ))}
              </div>
            )}

            <Button
              size="sm"
              endContent={<ExternalLink className="w-3.5 h-3.5" />}
              onPress={() => navigate(`/docs/${encodeURIComponent(selectedNode.id)}`)}
              className="w-full bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-8"
            >
              {t('graph.openDoc')}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};
