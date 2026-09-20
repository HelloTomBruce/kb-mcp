import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Input,
  Modal,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  useDisclosure,
  Spinner,
  Tooltip,
} from '@heroui/react';
import {
  Layers,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { DocTypeInfo } from '../../types';

export const TypesPage: React.FC = () => {
  const queryClient = useQueryClient();
  const { isOpen, onOpen, onClose } = useDisclosure();
  const [editingName, setEditingName] = useState<string | null>(null);

  // Form states
  const [name, setName] = useState('');
  const [label, setLabel] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#71717a');

  // Edit states
  const [editLabel, setEditLabel] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editColor, setEditColor] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['types'],
    queryFn: () => api.getTypes(),
  });

  const createMutation = useMutation({
    mutationFn: () => api.createType({ name, label, description, color }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['types'] });
      onClose();
      setName('');
      setLabel('');
      setDescription('');
      toast.success('Document type created successfully.');
    },
    onError: (err: any) => toast.error(`Failed to create type: ${err.message}`),
  });

  const updateMutation = useMutation({
    mutationFn: (typeName: string) =>
      api.updateType(typeName, {
        label: editLabel,
        description: editDescription,
        color: editColor,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['types'] });
      setEditingName(null);
      toast.success('Document type updated.');
    },
    onError: (err: any) => toast.error(`Failed to update type: ${err.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (typeName: string) => api.deleteType(typeName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['types'] });
      toast.success('Document type deleted.');
    },
    onError: (err: any) => toast.error(`Failed to delete type: ${err.message}`),
  });

  const handleStartEdit = (t: DocTypeInfo) => {
    setEditingName(t.name);
    setEditLabel(t.label || t.name);
    setEditDescription(t.description || '');
    setEditColor(t.color || '#71717a');
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" label="Loading schema types..." />
      </div>
    );
  }

  const typesList = data?.types || [];
  const stats = data?.stats || { total: 0, builtin: 0, custom: 0, total_docs: 0 };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
            <Layers className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
            Document Types Management
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Configure metadata taxonomies, system schemas, and document classification tags
          </p>
        </div>

        <Button
          startContent={<Plus className="w-4 h-4" />}
          onPress={onOpen}
          size="sm"
          className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
        >
          Add Custom Type
        </Button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs">
          <div className="text-[11px] font-medium text-zinc-500 uppercase">Total Types</div>
          <div className="text-xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">{stats.total}</div>
        </div>

        <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs">
          <div className="text-[11px] font-medium text-zinc-500 uppercase">Built-in Types</div>
          <div className="text-xl font-bold text-zinc-700 dark:text-zinc-300 mt-1 font-mono">{stats.builtin}</div>
        </div>

        <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs">
          <div className="text-[11px] font-medium text-zinc-500 uppercase">Custom Types</div>
          <div className="text-xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">{stats.custom}</div>
        </div>

        <div className="p-4 rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs">
          <div className="text-[11px] font-medium text-zinc-500 uppercase">Total Docs</div>
          <div className="text-xl font-bold text-zinc-900 dark:text-white mt-1 font-mono">{stats.total_docs}</div>
        </div>
      </div>

      {/* Table Container */}
      <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] overflow-hidden shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-white/[0.08] text-zinc-500 text-left bg-zinc-50/50 dark:bg-white/[0.02]">
                <th className="p-4 font-medium uppercase text-[11px]">IDENTIFIER</th>
                <th className="p-4 font-medium uppercase text-[11px]">DISPLAY NAME</th>
                <th className="p-4 font-medium uppercase text-[11px]">COLOR</th>
                <th className="p-4 font-medium uppercase text-[11px]">DOCUMENTS</th>
                <th className="p-4 font-medium uppercase text-[11px]">NATURE</th>
                <th className="p-4 font-medium uppercase text-[11px] text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-white/[0.04]">
              {typesList.map((t: DocTypeInfo) => {
                const isEditing = editingName === t.name;
                const hasDocs = (t.doc_count ?? 0) > 0;

                return (
                  <tr key={t.name} className="hover:bg-zinc-50/80 dark:hover:bg-white/[0.02] transition-colors">
                    {/* Identifier */}
                    <td className="p-4 font-mono font-semibold text-zinc-900 dark:text-zinc-200">
                      {t.name}
                    </td>

                    {/* Display Label & Description */}
                    <td className="p-4">
                      {isEditing ? (
                        <div className="space-y-1.5 max-w-xs">
                          <Input
                            size="sm"
                            value={editLabel}
                            onValueChange={setEditLabel}
                            placeholder="Display name"
                            className="text-xs"
                            classNames={{
                              inputWrapper: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-lg min-h-8 text-xs',
                            }}
                          />
                          <Input
                            size="sm"
                            value={editDescription}
                            onValueChange={setEditDescription}
                            placeholder="Description"
                            className="text-xs"
                            classNames={{
                              inputWrapper: 'bg-white dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-lg min-h-8 text-xs',
                            }}
                          />
                        </div>
                      ) : (
                        <div>
                          <div className="font-semibold text-zinc-900 dark:text-zinc-200">
                            {t.label || t.name}
                          </div>
                          {t.description && (
                            <div className="text-[11px] text-zinc-500 truncate max-w-sm mt-0.5">
                              {t.description}
                            </div>
                          )}
                        </div>
                      )}
                    </td>

                    {/* Color */}
                    <td className="p-4">
                      {isEditing ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="color"
                            value={editColor}
                            onChange={(e) => setEditColor(e.target.value)}
                            className="w-7 h-7 rounded border border-zinc-300 dark:border-white/20 cursor-pointer bg-transparent"
                          />
                          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">{editColor}</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span
                            className="w-3.5 h-3.5 rounded-full border border-zinc-300 dark:border-white/20"
                            style={{ backgroundColor: t.color || '#71717a' }}
                          />
                          <span className="font-mono text-zinc-500 dark:text-zinc-400 text-xs">{t.color || '#71717a'}</span>
                        </div>
                      )}
                    </td>

                    {/* Doc Count */}
                    <td className="p-4 font-mono font-medium text-zinc-800 dark:text-zinc-300">
                      {t.doc_count ?? 0}
                    </td>

                    {/* Builtin / Custom */}
                    <td className="p-4">
                      {t.builtin ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-zinc-100 dark:bg-white/[0.05] text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-white/[0.08]">
                          Built-in
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/40">
                          Custom
                        </span>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="p-4 text-right">
                      {isEditing ? (
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            onPress={() => updateMutation.mutate(t.name)}
                            isLoading={updateMutation.isPending}
                            className="text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 rounded-full w-7 h-7"
                            title="Save"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            onPress={() => setEditingName(null)}
                            className="text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-full w-7 h-7"
                            title="Cancel"
                          >
                            <X className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            isIconOnly
                            size="sm"
                            variant="light"
                            onPress={() => handleStartEdit(t)}
                            className="text-zinc-400 hover:text-zinc-900 dark:hover:text-white rounded-full w-7 h-7"
                            title="Edit Type"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </Button>

                          {!t.builtin && (
                            <Tooltip
                              content={hasDocs ? `Cannot delete: ${t.doc_count} document(s) are using this type` : 'Delete Custom Type'}
                              color={hasDocs ? 'danger' : 'default'}
                              className="text-xs"
                            >
                              <span>
                                <Button
                                  isIconOnly
                                  size="sm"
                                  variant="light"
                                  isDisabled={hasDocs}
                                  onPress={() => {
                                    if (window.confirm(`Are you sure you want to delete custom type "${t.name}"?`)) {
                                      deleteMutation.mutate(t.name);
                                    }
                                  }}
                                  className={`${
                                    hasDocs
                                      ? 'opacity-30 cursor-not-allowed text-zinc-400 dark:text-zinc-600'
                                      : 'text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40'
                                  } rounded-full w-7 h-7`}
                                  title="Delete Type"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </Button>
                              </span>
                            </Tooltip>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create Modal */}
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        placement="center"
        classNames={{
          base: 'bg-white dark:bg-[#0d0d11] border border-zinc-200 dark:border-white/[0.1] rounded-2xl text-zinc-900 dark:text-zinc-100 shadow-xl',
          header: 'border-b border-zinc-200 dark:border-white/[0.08]',
          footer: 'border-t border-zinc-200 dark:border-white/[0.08]',
        }}
      >
        <ModalContent>
          <ModalHeader className="font-bold text-base text-zinc-900 dark:text-white flex items-center gap-2">
            <Plus className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
            Add Custom Document Type
          </ModalHeader>
          <ModalBody className="space-y-3 py-4 text-xs">
            <div className="space-y-1">
              <label className="text-zinc-600 dark:text-zinc-400 font-medium">Type Identifier (Slug)</label>
              <Input
                size="sm"
                variant="bordered"
                placeholder="e.g. requirement, rfc, prompt"
                value={name}
                onValueChange={setName}
                className="font-mono text-xs"
                classNames={{
                  inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl',
                }}
              />
              <span className="text-[10px] text-zinc-500">Lowercase letters, numbers, and dashes only</span>
            </div>

            <div className="space-y-1">
              <label className="text-zinc-600 dark:text-zinc-400 font-medium">Display Name (Label)</label>
              <Input
                size="sm"
                variant="bordered"
                placeholder="e.g. 需求规格说明"
                value={label}
                onValueChange={setLabel}
                classNames={{
                  inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl',
                }}
              />
            </div>

            <div className="space-y-1">
              <label className="text-zinc-600 dark:text-zinc-400 font-medium">Description</label>
              <Input
                size="sm"
                variant="bordered"
                placeholder="Brief description of this type's purpose"
                value={description}
                onValueChange={setDescription}
                classNames={{
                  inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl',
                }}
              />
            </div>

            <div className="space-y-1">
              <label className="text-zinc-600 dark:text-zinc-400 font-medium">Theme Color</label>
              <div className="flex items-center gap-3">
                <input
                  type="color"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="w-9 h-9 rounded-lg border border-zinc-300 dark:border-white/20 cursor-pointer bg-transparent"
                />
                <Input
                  size="sm"
                  variant="bordered"
                  value={color}
                  onValueChange={setColor}
                  className="font-mono text-xs w-32"
                  classNames={{
                    inputWrapper: 'bg-zinc-50 dark:bg-zinc-900/60 border-zinc-200 dark:border-white/[0.08] rounded-xl',
                  }}
                />
              </div>
            </div>
          </ModalBody>
          <ModalFooter>
            <Button
              size="sm"
              variant="light"
              onPress={onClose}
              className="text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white rounded-full text-xs"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              isLoading={createMutation.isPending}
              isDisabled={!name.trim()}
              onPress={() => createMutation.mutate()}
              className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 px-4"
            >
              Create Type
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </div>
  );
};
