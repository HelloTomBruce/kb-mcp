export interface DocumentItem {
  id: string;
  type: string;
  title: string;
  body: string;
  tags: string[];
  aliases?: string[];
  source?: string;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
}

export interface LinkItem {
  from_id: string;
  to_id: string;
  rel: string;
  created_at: string;
}

export interface SearchHit {
  doc: DocumentItem;
  score: number;
  channel: string;
  snippet?: string;
  neighbors?: Array<{
    from_id: string;
    to_id: string;
    rel: string;
    doc?: DocumentItem;
  }>;
}

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
  auto_fixable?: boolean;
}

export interface DoctorReport {
  ok: boolean;
  checks: DoctorCheck[];
}

export interface StatsResponse {
  stats: {
    documents?: number;
    docs?: number;
    links: number;
    tags?: number;
    types?: number;
    [key: string]: any;
  };
  type_counts: Array<{ type: string; count: number }>;
  tag_counts: Array<{ tag: string; count: number }>;
  recent_docs: DocumentItem[];
  doctor_report: DoctorReport;
  embed_enabled: boolean;
  embed_dim: number | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  tags: string[];
  title?: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
  rel: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface VersionItem {
  id: number;
  doc_id: string;
  version: number;
  title: string;
  body: string;
  created_at: string;
  diff?: string;
}

export interface DocTypeInfo {
  name: string;
  label?: string;
  description?: string;
  color?: string;
  builtin?: boolean;
  doc_count?: number;
}

export interface GitStatusInfo {
  ok: boolean;
  is_git?: boolean;
  branch?: string;
  clean?: boolean;
  ahead?: number;
  behind?: number;
  untracked?: string[];
  modified?: string[];
  unstaged?: Array<{ status: string; path: string }>;
  staged?: Array<{ status: string; path: string }>;
  sync_dir?: string;
  git_dir?: string;
  vault_name?: string;
  status_raw?: string;
  pending_export?: {
    total: number;
    added: string[];
    modified: string[];
    deleted: string[];
  };
  remote?: string;
  error?: string;
}

export interface GitDiffResponse {
  ok: boolean;
  diff?: string;
  pending_diffs?: Record<string, string>;
  error?: string;
}

export interface GitCommitItem {
  hash: string;
  author: string;
  date: string;
  message: string;
}

export interface SchedulerTaskItem {
  name: string;
  description?: string;
  interval_seconds?: number;
  cron?: string;
  enabled: boolean;
  last_run?: string;
  last_status?: string;
  last_duration_ms?: number;
  next_run?: string;
}

export interface SchedulerHistoryItem {
  id?: number;
  task_name: string;
  status: string;
  duration_ms: number;
  error?: string;
  timestamp?: string;
  created_at?: string;
}
