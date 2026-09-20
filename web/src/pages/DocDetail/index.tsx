import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Input,
  Button,
  Tabs,
  Tab,
  Spinner,
  Select,
  SelectItem,
} from '@heroui/react';
import {
  ArrowLeft,
  Save,
  Trash2,
  RotateCcw,
  Network,
  History,
  Edit3,
  Copy,
  Check,
  Plus,
  ExternalLink,
  FileCode,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { DocTypeInfo } from '../../types';
import { MarkdownRenderer } from '../../components/MarkdownRenderer';
import { DiffViewer } from '../../components/DiffViewer';
import { TypeBadge, TagBadge, TYPE_LABELS } from '../../components/Badge';

const STANDARD_RELATIONS = [
  'relates-to',
  'depends-on',
  'supersedes',
  'superseded-by',
  'governs',
  'blocks',
  'is_influence',
  'derives-from',
  'implements',
  'tests',
];

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

export const DocDetailPage: React.FC = () => {
  const { docId } = useParams<{ docId: string }>();
  const isNew = docId === 'new' || !docId;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<string>('content');
  const [isEditing, setIsEditing] = useState(isNew);
  const [editorMode, setEditorMode] = useState<'split' | 'edit' | 'preview'>(isNew ? 'split' : 'preview');

  // Form states
  const [idValue, setIdValue] = useState('');
  const [typeValue, setTypeValue] = useState('decision');
  const [titleValue, setTitleValue] = useState('');
  const [bodyValue, setBodyValue] = useState('');
  const [tagsValue, setTagsValue] = useState('');
  const [sourceValue, setSourceValue] = useState('');

  // Relation form
  const [newTargetId, setNewTargetId] = useState('');
  const [newRelType, setNewRelType] = useState('depends-on');

  // Diff comparison
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  // Load existing doc
  const { data: doc, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['doc', docId],
    queryFn: () => api.getDoc(decodeURIComponent(docId!)),
    enabled: !isNew && !!docId,
  });

  // Load versions
  const { data: versionsData, refetch: refetchVersions } = useQuery({
    queryKey: ['doc-versions', docId],
    queryFn: () => api.getVersions(decodeURIComponent(docId!)),
    enabled: !isNew && !!docId && activeTab === 'history',
  });

  // Load all links
  const { data: allLinksData, refetch: refetchLinks } = useQuery({
    queryKey: ['links'],
    queryFn: () => api.getLinks(),
    enabled: !isNew && !!docId && activeTab === 'links',
  });

  // Load types
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

  useEffect(() => {
    if (doc && !isNew) {
      setIdValue(doc.id);
      setTypeValue(doc.type);
      setTitleValue(doc.title);
      setBodyValue(doc.body);
      setTagsValue((doc.tags || []).join(', '));
      setSourceValue(doc.source || '');
    }
  }, [doc, isNew]);

  const handleCopyId = () => {
    navigator.clipboard.writeText(idValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Save / Update mutation
  const saveMutation = useMutation({
    mutationFn: async () => {
      const tagsArray = tagsValue
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);

      if (isNew) {
        return api.createDoc({
          id: idValue.trim() || undefined,
          type: typeValue,
          title: titleValue.trim(),
          body: bodyValue,
          tags: tagsArray,
          source: sourceValue.trim() || undefined,
        });
      } else {
        return api.updateDoc(doc!.id, {
          title: titleValue.trim(),
          body: bodyValue,
          tags: tagsArray,
          source: sourceValue.trim() || undefined,
        });
      }
    },
    onSuccess: (savedDoc) => {
      queryClient.invalidateQueries({ queryKey: ['docs'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      if (isNew) {
        toast.success('Document created successfully.');
        navigate(`/docs/${encodeURIComponent(savedDoc.id)}`, { replace: true });
        setIsEditing(false);
        setEditorMode('preview');
      } else {
        refetch();
        setIsEditing(false);
        setEditorMode('preview');
        toast.success('Document saved successfully.');
      }
    },
    onError: (err: any) => {
      toast.error(`Save failed: ${err.message}`);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async () => {
      return api.deleteDoc(doc!.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docs'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      toast.success('Document deleted successfully.');
      navigate('/docs');
    },
    onError: (err: any) => {
      toast.error(`Delete failed: ${err.message}`);
    },
  });

  // Add Link
  const handleAddLink = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTargetId.trim()) return;
    try {
      await api.createLink({
        from_id: doc!.id,
        to_id: newTargetId.trim(),
        rel: newRelType,
      });
      setNewTargetId('');
      refetch();
      refetchLinks();
      toast.success('Relation link added.');
    } catch (err: any) {
      toast.error(`Add link failed: ${err.message}`);
    }
  };

  // Remove Link
  const handleRemoveLink = async (fromId: string, toId: string, rel: string) => {
    if (!confirm(`Are you sure you want to remove link [${fromId}] --(${rel})--> [${toId}]?`)) return;
    try {
      await api.deleteLink({ from_id: fromId, to_id: toId, rel });
      refetch();
      refetchLinks();
      toast.success('Relation link removed.');
    } catch (err: any) {
      toast.error(`Remove link failed: ${err.message}`);
    }
  };

  // Restore version
  const handleRestoreVersion = async (v: number) => {
    if (!confirm(`Are you sure you want to rollback to version ${v}?`)) return;
    try {
      await api.restoreVersion(doc!.id, v);
      refetch();
      refetchVersions();
      toast.success(`Successfully restored version ${v}.`);
    } catch (err: any) {
      toast.error(`Restore failed: ${err.message}`);
    }
  };

  if (!isNew && isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label="Loading document details..." />
      </div>
    );
  }

  if (!isNew && isError) {
    return (
      <div className="p-6 rounded-2xl bg-red-950/20 border border-red-500/20 space-y-3">
        <h3 className="font-semibold text-base text-red-400">Document not found</h3>
        <p className="text-xs text-red-300">{(error as Error)?.message}</p>
        <Button
          as={Link}
          to="/docs"
          size="sm"
          startContent={<ArrowLeft className="w-3.5 h-3.5" />}
          className="bg-white/[0.05] hover:bg-white/[0.1] text-zinc-200 border border-white/[0.08] text-xs font-semibold rounded-full"
        >
          Back to Documents
        </Button>
      </div>
    );
  }

  const outboundLinks = (allLinksData?.items || []).filter((l) => l.from_id === doc?.id);
  const inboundLinks = (allLinksData?.items || []).filter((l) => l.to_id === doc?.id);

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Button
            isIconOnly
            size="sm"
            onPress={() => navigate('/docs')}
            className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08] rounded-full w-8 h-8"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              {isNew ? 'Create New Document' : doc?.title || 'Document'}
            </h1>
            {!isNew && (
              <div className="flex items-center gap-2 mt-1 text-xs text-zinc-500 font-mono">
                <span>{doc?.id}</span>
                <button onClick={handleCopyId} className="hover:text-black dark:hover:text-white">
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {!isNew && (
            <>
              {isEditing ? (
                <Button
                  size="sm"
                  onPress={() => {
                    setIsEditing(false);
                    setEditorMode('preview');
                  }}
                  className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08] text-xs rounded-full h-9 px-4"
                >
                  Cancel
                </Button>
              ) : (
                <Button
                  size="sm"
                  startContent={<Edit3 className="w-3.5 h-3.5" />}
                  onPress={() => {
                    setIsEditing(true);
                    setEditorMode('split');
                  }}
                  className="bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.05] dark:hover:bg-white/[0.1] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.08] text-xs font-semibold rounded-full h-9 px-4"
                >
                  Edit
                </Button>
              )}

              <Button
                isIconOnly
                size="sm"
                onPress={() => {
                  if (confirm('Are you sure you want to delete this document?')) {
                    deleteMutation.mutate();
                  }
                }}
                className="text-zinc-400 hover:text-red-500 rounded-full w-8 h-8"
                title="Delete Document"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </>
          )}

          {(isEditing || isNew) && (
            <Button
              size="sm"
              startContent={<Save className="w-4 h-4" />}
              isLoading={saveMutation.isPending}
              isDisabled={!titleValue.trim()}
              onPress={() => saveMutation.mutate()}
              className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
            >
              {isNew ? 'Create Document' : 'Save Changes'}
            </Button>
          )}
        </div>
      </div>

      {/* Tabs */}
      {!isNew && (
        <Tabs
          selectedKey={activeTab}
          onSelectionChange={(k) => setActiveTab(String(k))}
          variant="underlined"
          classNames={{
            tabList: 'gap-6 w-full relative rounded-none p-0 border-b border-zinc-200 dark:border-white/[0.08]',
            tab: 'max-w-fit px-0 h-10 text-xs font-medium',
          }}
        >
          <Tab
            key="content"
            title={
              <div className="flex items-center space-x-2">
                <FileCode className="w-4 h-4" />
                <span>Content & Markdown</span>
              </div>
            }
          />
          <Tab
            key="links"
            title={
              <div className="flex items-center space-x-2">
                <Network className="w-4 h-4" />
                <span>Graph Relations ({outboundLinks.length + inboundLinks.length})</span>
              </div>
            }
          />
          <Tab
            key="history"
            title={
              <div className="flex items-center space-x-2">
                <History className="w-4 h-4" />
                <span>Version History</span>
              </div>
            }
          />
        </Tabs>
      )}

      {/* TAB 1: Content & Markdown */}
      {(activeTab === 'content' || isNew) && (
        <div className="space-y-6">
          {/* Metadata Form */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label className="block text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
                  Document Type
                </label>
                {isEditing || isNew ? (
                  <Select
                    size="sm"
                    aria-label="Document Type"
                    selectedKeys={typeValue ? [typeValue] : []}
                    onChange={(e) => setTypeValue(e.target.value)}
                    variant="bordered"
                    disableAnimation
                    classNames={{
                      trigger: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-8 text-xs',
                      value: 'text-xs text-zinc-800 dark:text-zinc-200 font-medium',
                    }}
                  >
                    {availableTypes.map((t) => (
                      <SelectItem key={t.name} textValue={t.label} className="text-xs">
                        {t.label}
                      </SelectItem>
                    ))}
                  </Select>
                ) : (
                  <div className="pt-1">
                    <TypeBadge type={typeValue} />
                  </div>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
                  Document ID
                </label>
                {isNew ? (
                  <Input
                    size="sm"
                    variant="bordered"
                    value={idValue}
                    onValueChange={setIdValue}
                    placeholder="Auto-generated if empty"
                    className="font-mono text-xs"
                    classNames={{
                      inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-8 text-xs',
                    }}
                  />
                ) : (
                  <div className="text-xs font-mono text-zinc-700 dark:text-zinc-300 pt-1.5 truncate">
                    {idValue}
                  </div>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
                  Tags (comma-separated)
                </label>
                {isEditing || isNew ? (
                  <Input
                    size="sm"
                    variant="bordered"
                    value={tagsValue}
                    onValueChange={setTagsValue}
                    placeholder="sqlite, backend, mcp"
                    classNames={{
                      inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-8 text-xs',
                    }}
                  />
                ) : (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {tagsValue
                      .split(',')
                      .map((t) => t.trim())
                      .filter(Boolean)
                      .map((t) => (
                        <TagBadge key={t} tag={t} />
                      ))}
                  </div>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
                  Source File
                </label>
                {isEditing || isNew ? (
                  <Input
                    size="sm"
                    variant="bordered"
                    value={sourceValue}
                    onValueChange={setSourceValue}
                    placeholder="docs/arch.md"
                    className="font-mono text-xs"
                    classNames={{
                      inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-8 text-xs',
                    }}
                  />
                ) : (
                  <div className="text-xs text-zinc-500 pt-1.5 truncate font-mono">
                    {sourceValue || 'None'}
                  </div>
                )}
              </div>

              <div className="md:col-span-2 lg:col-span-4">
                <label className="block text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
                  Document Title
                </label>
                {isEditing || isNew ? (
                  <Input
                    size="sm"
                    variant="bordered"
                    value={titleValue}
                    onValueChange={setTitleValue}
                    placeholder="Title of this knowledge item..."
                    className="font-semibold"
                    classNames={{
                      inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-9 text-xs',
                    }}
                  />
                ) : (
                  <div className="text-base font-semibold text-zinc-900 dark:text-white pt-1">
                    {titleValue}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Editor Header Mode switch */}
          {isEditing && (
            <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs px-4 py-2.5 flex items-center justify-between">
              <span className="font-semibold text-zinc-500 uppercase tracking-wider text-[11px]">
                Markdown Content Editor
              </span>
              <div className="flex items-center p-0.5 rounded-full bg-zinc-100 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/[0.08]">
                {(['edit', 'split', 'preview'] as const).map((m) => {
                  const isActive = editorMode === m;
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setEditorMode(m)}
                      className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-all ${
                        isActive
                          ? 'bg-white dark:bg-white text-black dark:text-black font-semibold shadow-xs'
                          : 'text-zinc-600 dark:text-zinc-400 hover:text-black dark:hover:text-zinc-100'
                      }`}
                    >
                      {m}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Body Box */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs overflow-hidden">
            {!isEditing ? (
              <div className="p-8">
                {bodyValue ? (
                  <MarkdownRenderer content={bodyValue} />
                ) : (
                  <div className="text-zinc-500 italic text-xs">No body content.</div>
                )}
              </div>
            ) : editorMode === 'split' ? (
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-zinc-200 dark:divide-white/[0.08] min-h-[500px]">
                <textarea
                  value={bodyValue}
                  onChange={(e) => setBodyValue(e.target.value)}
                  placeholder="Write your markdown knowledge documentation here..."
                  className="w-full h-full p-6 bg-zinc-50/50 dark:bg-black text-zinc-900 dark:text-zinc-100 font-mono text-xs resize-none focus:outline-hidden leading-relaxed"
                  spellCheck={false}
                />
                <div className="p-6 overflow-y-auto max-h-[600px]">
                  <MarkdownRenderer content={bodyValue || '*Preview appears here...*'} />
                </div>
              </div>
            ) : editorMode === 'edit' ? (
              <textarea
                value={bodyValue}
                onChange={(e) => setBodyValue(e.target.value)}
                placeholder="Write your markdown knowledge documentation here..."
                className="w-full min-h-[500px] p-6 bg-zinc-50/50 dark:bg-black text-zinc-900 dark:text-zinc-100 font-mono text-xs resize-y focus:outline-hidden leading-relaxed"
                spellCheck={false}
              />
            ) : (
              <div className="p-8 min-h-[400px]">
                <MarkdownRenderer content={bodyValue || '*Preview appears here...*'} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: Relations (Links) */}
      {activeTab === 'links' && !isNew && (
        <div className="space-y-6">
          {/* Add Link Form */}
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-3">
            <h3 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
              <Plus className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Add Relation Link Edge
            </h3>
            <form onSubmit={handleAddLink} className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-xs font-semibold px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-white/[0.05] text-zinc-800 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08]">
                {doc?.id}
              </span>

              <div className="w-48">
                <Select
                  size="sm"
                  aria-label="Relation Type"
                  selectedKeys={newRelType ? [newRelType] : []}
                  onChange={(e) => setNewRelType(e.target.value)}
                  variant="bordered"
                  disableAnimation
                  classNames={{
                    trigger: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl min-h-9',
                    value: 'text-xs text-zinc-800 dark:text-zinc-200 font-mono',
                  }}
                >
                  {STANDARD_RELATIONS.map((r) => (
                    <SelectItem key={r} textValue={r} className="font-mono text-xs">
                      {r}
                    </SelectItem>
                  ))}
                </Select>
              </div>

              <Input
                size="sm"
                variant="bordered"
                value={newTargetId}
                onValueChange={setNewTargetId}
                placeholder="Target Document ID (e.g. decision/use-sqlite)"
                className="flex-1 min-w-[240px] font-mono text-xs"
                classNames={{
                  inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 rounded-xl min-h-9 text-xs shadow-2xs',
                  input: 'text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500',
                }}
              />

              <Button
                type="submit"
                size="sm"
                className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
              >
                Connect Link
              </Button>
            </form>
          </div>

          {/* Links Tables */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Outbound */}
            <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-3">
              <h4 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center justify-between">
                <span>Outbound Links (This Doc → Target)</span>
                <span className="text-xs text-zinc-500 font-mono">({outboundLinks.length})</span>
              </h4>
              <div className="divide-y divide-zinc-100 dark:divide-white/[0.06]">
                {outboundLinks.length > 0 ? (
                  outboundLinks.map((l, idx) => (
                    <div key={idx} className="py-2.5 flex items-center justify-between text-xs font-mono">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded-full text-[10px] bg-zinc-100 dark:bg-white/[0.04] text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08]">
                          {l.rel}
                        </span>
                        <Link
                          to={`/docs/${encodeURIComponent(l.to_id)}`}
                          className="hover:text-black dark:hover:text-white flex items-center gap-1 text-zinc-700 dark:text-zinc-300 font-semibold"
                        >
                          {l.to_id} <ExternalLink className="w-3 h-3 text-zinc-400" />
                        </Link>
                      </div>
                      <Button
                        isIconOnly
                        size="sm"
                        variant="light"
                        onPress={() => handleRemoveLink(l.from_id, l.to_id, l.rel)}
                        className="text-zinc-400 hover:text-red-500 rounded-full w-7 h-7"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  ))
                ) : (
                  <div className="py-4 text-xs text-zinc-500">No outbound links.</div>
                )}
              </div>
            </div>

            {/* Inbound */}
            <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-3">
              <h4 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center justify-between">
                <span>Inbound Links (Source → This Doc)</span>
                <span className="text-xs text-zinc-500 font-mono">({inboundLinks.length})</span>
              </h4>
              <div className="divide-y divide-zinc-100 dark:divide-white/[0.06]">
                {inboundLinks.length > 0 ? (
                  inboundLinks.map((l, idx) => (
                    <div key={idx} className="py-2.5 flex items-center justify-between text-xs font-mono">
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/docs/${encodeURIComponent(l.from_id)}`}
                          className="hover:text-black dark:hover:text-white flex items-center gap-1 text-zinc-700 dark:text-zinc-300 font-semibold"
                        >
                          {l.from_id} <ExternalLink className="w-3 h-3 text-zinc-400" />
                        </Link>
                        <span className="px-2 py-0.5 rounded-full text-[10px] bg-zinc-100 dark:bg-white/[0.04] text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-white/[0.08]">
                          {l.rel}
                        </span>
                      </div>
                      <Button
                        isIconOnly
                        size="sm"
                        variant="light"
                        onPress={() => handleRemoveLink(l.from_id, l.to_id, l.rel)}
                        className="text-zinc-400 hover:text-red-500 rounded-full w-7 h-7"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  ))
                ) : (
                  <div className="py-4 text-xs text-zinc-500">No inbound links.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: History & Snapshots */}
      {activeTab === 'history' && !isNew && (
        <div className="space-y-6">
          <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-5 space-y-4">
            <h3 className="font-semibold text-sm text-zinc-900 dark:text-white">
              Historical Snapshots & Version Diff
            </h3>
            {versionsData?.items && versionsData.items.length > 0 ? (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {versionsData.items.map((v) => (
                    <button
                      key={v.version}
                      type="button"
                      onClick={() => setSelectedVersion(v.version === selectedVersion ? null : v.version)}
                      className={`px-3 py-1.5 rounded-full text-xs font-mono transition-all ${
                        selectedVersion === v.version
                          ? 'bg-black dark:bg-white text-white dark:text-black font-semibold shadow-xs'
                          : 'bg-zinc-100 dark:bg-white/[0.04] text-zinc-600 dark:text-zinc-400 hover:text-black dark:hover:text-white border border-zinc-200 dark:border-white/[0.08]'
                      }`}
                    >
                      v{v.version} ({v.created_at ? v.created_at.split('T')[0] : ''})
                    </button>
                  ))}
                </div>

                {selectedVersion !== null && (
                  <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-white/[0.08] space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                        Diff for Version {selectedVersion} vs Current
                      </h4>
                      <Button
                        size="sm"
                        startContent={<RotateCcw className="w-3 h-3" />}
                        onPress={() => handleRestoreVersion(selectedVersion)}
                        className="bg-amber-500 text-black font-semibold text-xs rounded-full hover:bg-amber-400 h-8"
                      >
                        Rollback to v{selectedVersion}
                      </Button>
                    </div>

                    <div className="rounded-xl overflow-hidden border border-zinc-200 dark:border-white/[0.08]">
                      <DiffViewer
                        diffText={
                          versionsData.items.find((v) => v.version === selectedVersion)?.diff ||
                          'No diff text recorded.'
                        }
                      />
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-zinc-500 py-4">No historical versions found for this document.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
