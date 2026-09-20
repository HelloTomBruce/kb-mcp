import React from 'react';

interface DiffViewerProps {
  diffText: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ diffText }) => {
  if (!diffText || !diffText.trim()) {
    return <div className="text-sm text-slate-500 italic p-4">No differences found.</div>;
  }

  const lines = diffText.split('\n');

  return (
    <div className="font-mono text-xs rounded-lg overflow-x-auto border border-slate-200 dark:border-slate-800 bg-slate-900 text-slate-100 p-4">
      {lines.map((line, idx) => {
        let lineClass = 'text-slate-400';
        let bgClass = '';
        if (line.startsWith('+') && !line.startsWith('+++')) {
          lineClass = 'text-emerald-400';
          bgClass = 'bg-emerald-950/40 -mx-4 px-4';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          lineClass = 'text-rose-400';
          bgClass = 'bg-rose-950/40 -mx-4 px-4';
        } else if (line.startsWith('@@')) {
          lineClass = 'text-cyan-400 font-bold';
        }

        return (
          <div key={idx} className={`${lineClass} ${bgClass} py-0.5 whitespace-pre`}>
            {line || ' '}
          </div>
        );
      })}
    </div>
  );
};
