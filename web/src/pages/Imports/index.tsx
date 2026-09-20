import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Checkbox,
} from '@heroui/react';
import {
  Upload,
  Download,
  FileArchive,
  FolderInput,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import { api } from '../../api/client';
import { toast } from 'sonner';

export const ImportsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(false);
  const [importReport, setImportReport] = useState<any>(null);

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFile) throw new Error('Please select a .zip archive first.');
      return api.uploadImportZip(selectedFile, dryRun);
    },
    onSuccess: (data) => {
      setImportReport(data.report || data);
      queryClient.invalidateQueries();
      if (!dryRun) {
        toast.success('Import completed successfully.');
      } else {
        toast.info('Dry run preview completed.');
      }
    },
    onError: (err: any) => toast.error(`Import failed: ${err.message}`),
  });

  const handleDownloadExport = () => {
    window.location.href = api.getExportDownloadUrl();
  };

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white flex items-center gap-2.5">
          <FolderInput className="w-6 h-6 text-zinc-500 dark:text-zinc-400" />
          Bulk Markdown Import & Export
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          Import folders of Markdown files with YAML frontmatter into SQLite, or export knowledge base as a portable archive
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Import Box */}
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-5">
          <div>
            <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
              <Upload className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              Import Markdown Archive (.zip)
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              Upload a ZIP archive containing `.md` files. Each file's YAML frontmatter (e.g. `type: decision`, `tags: [...]`) will be parsed and indexed.
            </p>
          </div>

          <div className="border border-dashed border-zinc-300 dark:border-white/20 rounded-2xl p-6 text-center space-y-3 hover:border-zinc-400 dark:hover:border-white/40 transition-colors bg-zinc-50/50 dark:bg-white/[0.01]">
            <FileArchive className="w-8 h-8 text-zinc-400 dark:text-zinc-500 mx-auto" />
            <div className="text-xs text-zinc-600 dark:text-zinc-300">
              {selectedFile ? (
                <span className="font-semibold text-zinc-900 dark:text-white font-mono">{selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
              ) : (
                <span className="text-zinc-400 dark:text-zinc-500">Select or drop a .zip archive here</span>
              )}
            </div>
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              className="hidden"
              id="file-upload"
            />
            <div>
              <label
                htmlFor="file-upload"
                className="inline-block px-4 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-white/[0.06] dark:hover:bg-white/[0.12] text-zinc-800 dark:text-zinc-200 border border-zinc-200 dark:border-white/[0.1] text-xs font-semibold rounded-full cursor-pointer transition-all"
              >
                Choose ZIP File
              </label>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2">
            <Checkbox
              size="sm"
              isSelected={dryRun}
              onValueChange={setDryRun}
              classNames={{ label: 'text-xs text-zinc-600 dark:text-zinc-400' }}
            >
              Dry Run (Preview changes)
            </Checkbox>

            <Button
              size="sm"
              isLoading={importMutation.isPending}
              isDisabled={!selectedFile}
              onPress={() => importMutation.mutate()}
              className="bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 px-4 shadow-sm"
            >
              {dryRun ? 'Run Preview' : 'Execute Import'}
            </Button>
          </div>
        </div>

        {/* Export Box */}
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 flex flex-col justify-between space-y-5">
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
                <Download className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                Export Vault as Markdown Zip
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed mt-1">
                Download the entire active knowledge repository as standard Markdown files with full YAML frontmatter headers.
              </p>
            </div>
            <div className="p-4 bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] rounded-xl text-xs space-y-2 text-zinc-600 dark:text-zinc-300">
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">✓ Includes all active documents & aliases</div>
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">✓ Preserves relation link annotations</div>
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">✓ 100% portable for Obsidian / Logseq / GitHub</div>
            </div>
          </div>

          <Button
            size="sm"
            startContent={<Download className="w-4 h-4" />}
            onPress={handleDownloadExport}
            className="w-full bg-black dark:bg-white text-white dark:text-black font-semibold text-xs rounded-full hover:bg-zinc-800 dark:hover:bg-zinc-200 h-9 shadow-sm"
          >
            Download Full Export Archive (.zip)
          </Button>
        </div>
      </div>

      {/* Import Report Panel */}
      {importReport && (
        <div className="rounded-2xl bg-white dark:bg-[#0d0d11]/80 backdrop-blur-md border border-zinc-200 dark:border-white/[0.08] shadow-xs p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-sm text-zinc-900 dark:text-white flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
              Import Execution Summary
            </h3>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] text-center">
              <div className="text-[11px] text-zinc-500 uppercase font-medium">Inserted (New)</div>
              <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 font-mono mt-1">
                {importReport.inserted ?? 0}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] text-center">
              <div className="text-[11px] text-zinc-500 uppercase font-medium">Updated</div>
              <div className="text-2xl font-bold text-amber-600 dark:text-amber-400 font-mono mt-1">
                {importReport.updated ?? 0}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-zinc-50 dark:bg-white/[0.02] border border-zinc-200 dark:border-white/[0.06] text-center">
              <div className="text-[11px] text-zinc-500 uppercase font-medium">Skipped (Unchanged)</div>
              <div className="text-2xl font-bold text-zinc-500 dark:text-zinc-400 font-mono mt-1">
                {importReport.skipped ?? 0}
              </div>
            </div>
          </div>

          {importReport.errors && importReport.errors.length > 0 && (
            <div className="mt-4 p-4 rounded-xl bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-500/20 space-y-2">
              <div className="text-xs font-semibold text-red-600 dark:text-red-400 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" /> Import Warnings & Errors ({importReport.errors.length})
              </div>
              <ul className="text-xs font-mono text-red-600 dark:text-red-300 space-y-1 list-disc pl-5 max-h-40 overflow-y-auto">
                {importReport.errors.map((err: string, idx: number) => (
                  <li key={idx}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
