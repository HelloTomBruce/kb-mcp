import React from 'react';
import { useTranslation } from 'react-i18next';

interface TypeBadgeProps {
  type: string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const TYPE_LABELS: Record<string, string> = {
  project: '项目/规划 (project)',
  decision: '架构决策 (decision)',
  lesson: '经验复盘 (lesson)',
  glossary: '术语定义 (glossary)',
  person: '团队角色 (person)',
  faq: '常见问答 (faq)',
  api: '接口约定 (api)',
  runbook: '运维手册 (runbook)',
  release: '发布记录 (release)',
};

export const TYPE_SHORT_LABELS: Record<string, string> = {
  project: '项目/规划',
  decision: '架构决策',
  lesson: '经验复盘',
  glossary: '术语定义',
  person: '团队角色',
  faq: '常见问答',
  api: '接口约定',
  runbook: '运维手册',
  release: '发布记录',
};

const TYPE_STYLES: Record<string, string> = {
  project: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800/50',
  decision: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50',
  lesson: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/50',
  glossary: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-950/40 dark:text-cyan-300 dark:border-cyan-800/50',
  person: 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-800/50',
  faq: 'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/40 dark:text-teal-300 dark:border-teal-800/50',
  api: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-800/50',
  runbook: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800/50',
  release: 'bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-950/40 dark:text-pink-300 dark:border-pink-800/50',
};

export const TypeBadge: React.FC<TypeBadgeProps> = ({ type, className = '', size = 'sm' }) => {
  const { t } = useTranslation();
  const normalized = type.toLowerCase();
  const label = t(`typeNames.${normalized}`, { defaultValue: TYPE_SHORT_LABELS[normalized] || type });
  const styleClass = TYPE_STYLES[normalized] || 'bg-zinc-100 text-zinc-700 border-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-800';
  const sizeClass = size === 'lg' ? 'text-xs px-2.5 py-1' : size === 'md' ? 'text-[11px] px-2 py-0.5' : 'text-[10px] px-2 py-0.5';

  return (
    <span
      className={`inline-flex items-center rounded-md font-medium border ${sizeClass} ${styleClass} ${className}`}
    >
      {label}
    </span>
  );
};

export const TagBadge: React.FC<{ tag: string; onClick?: () => void; size?: 'sm' | 'md' }> = ({
  tag,
  onClick,
  size = 'sm',
}) => {
  const sizeClass = size === 'md' ? 'text-xs px-2.5 py-0.5' : 'text-[10px] px-2 py-0.5';

  return (
    <span
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full font-mono bg-zinc-100 dark:bg-white/[0.04] text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-white/[0.08] hover:border-zinc-300 dark:hover:border-white/20 transition-all ${
        onClick ? 'cursor-pointer hover:text-black dark:hover:text-white' : ''
      } ${sizeClass}`}
    >
      #{tag}
    </span>
  );
};
