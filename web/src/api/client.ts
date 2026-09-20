import {
  DocumentItem,
  LinkItem,
  SearchHit,
  StatsResponse,
  GraphData,
  VersionItem,
  DoctorReport,
  DocTypeInfo,
  GitStatusInfo,
  GitDiffResponse,
  GitCommitItem,
  SchedulerTaskItem,
  SchedulerHistoryItem,
} from '../types';

const BASE_URL = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorMsg = `HTTP Error ${res.status}`;
    try {
      const data = await res.json();
      errorMsg = data.detail || data.error || errorMsg;
    } catch {
      // ignore json parse error
    }
    throw new Error(errorMsg);
  }
  return res.json();
}

export const api = {
  // ── Stats & Health ──────────────────────────────────────────────
  async getStats(): Promise<StatsResponse> {
    const res = await fetch(`${BASE_URL}/stats`);
    return handleResponse<StatsResponse>(res);
  },

  async getHealth(): Promise<{ ok: boolean; checks: any[]; db_path: string; schema_version: number; audit_log: any[] }> {
    const res = await fetch(`${BASE_URL}/health`);
    return handleResponse(res);
  },

  async getAudit(limit = 50): Promise<{ items: any[]; count: number }> {
    const res = await fetch(`${BASE_URL}/audit?limit=${limit}`);
    return handleResponse(res);
  },

  async fixDoctor(): Promise<DoctorReport> {
    const res = await fetch(`${BASE_URL}/doctor/fix`, { method: 'POST' });
    return handleResponse<DoctorReport>(res);
  },

  // ── Documents ───────────────────────────────────────────────────
  async getDocs(params?: {
    q?: string;
    type?: string;
    tag?: string;
    include_deleted?: boolean;
  }): Promise<{ items: DocumentItem[]; count: number }> {
    const query = new URLSearchParams();
    if (params?.q) query.set('q', params.q);
    if (params?.type) query.set('type', params.type);
    if (params?.tag) query.set('tag', params.tag);
    if (params?.include_deleted) query.set('include_deleted', 'true');

    const res = await fetch(`${BASE_URL}/docs?${query.toString()}`);
    const data = await handleResponse<any>(res);
    return {
      items: data.items || data.docs || [],
      count: data.count ?? (data.items?.length || 0),
    };
  },

  async getDoc(id: string): Promise<DocumentItem & { inbound_links?: LinkItem[]; outbound_links?: LinkItem[] }> {
    const res = await fetch(`${BASE_URL}/docs/${encodeURIComponent(id)}`);
    const data = await handleResponse<any>(res);
    const doc = data.doc || data;
    return {
      ...doc,
      inbound_links: data.backlinks || data.inbound_links || [],
      outbound_links: data.outlinks || data.outbound_links || [],
    };
  },

  async createDoc(data: {
    id?: string;
    type: string;
    title: string;
    body: string;
    tags?: string[];
    source?: string;
  }): Promise<DocumentItem> {
    const res = await fetch(`${BASE_URL}/docs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const resData = await handleResponse<any>(res);
    return resData.doc || resData;
  },

  async updateDoc(
    id: string,
    data: {
      title?: string;
      body?: string;
      tags?: string[];
      source?: string;
      deleted?: boolean;
    }
  ): Promise<DocumentItem> {
    const res = await fetch(`${BASE_URL}/docs/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const resData = await handleResponse<any>(res);
    return resData.doc || resData;
  },

  async deleteDoc(id: string): Promise<{ ok: boolean }> {
    const res = await fetch(`${BASE_URL}/docs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    return handleResponse<{ ok: boolean }>(res);
  },

  async getVersions(id: string): Promise<{ items: VersionItem[] }> {
    const res = await fetch(`${BASE_URL}/docs/${encodeURIComponent(id)}`);
    const data = await handleResponse<any>(res);
    return { items: data.history || [] };
  },

  async restoreVersion(id: string, version: number): Promise<DocumentItem> {
    const res = await fetch(`${BASE_URL}/docs/${encodeURIComponent(id)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version }),
    });
    const data = await handleResponse<any>(res);
    return data.doc || data;
  },

  // ── Search ──────────────────────────────────────────────────────
  async search(params: {
    q: string;
    mode?: 'hybrid' | 'lexical' | 'semantic' | 'fuzzy';
    type?: string;
    limit?: number;
    expand_graph?: boolean;
  }): Promise<{ items: SearchHit[]; count: number }> {
    const query = new URLSearchParams();
    query.set('query', params.q);
    query.set('q', params.q);
    if (params.mode) query.set('mode', params.mode);
    if (params.type) query.set('type', params.type);
    if (params.limit) query.set('limit', String(params.limit));
    if (params.expand_graph) query.set('expand_graph', 'true');

    const res = await fetch(`${BASE_URL}/search?${query.toString()}`);
    const data = await handleResponse<any>(res);
    const hits = data.hits || data.items || [];
    return {
      items: hits.map((h: any) => ({
        doc: h.doc || h,
        score: h.score ?? 1.0,
        channel: h.channel || 'hybrid',
        snippet: h.snippet,
        neighbors: h.neighbors,
      })),
      count: data.count ?? hits.length,
    };
  },

  // ── Types Management ────────────────────────────────────────────
  async getTypes(): Promise<{ types: DocTypeInfo[]; stats: { total: number; builtin: number; custom: number; total_docs: number } }> {
    const res = await fetch(`${BASE_URL}/types`);
    return handleResponse(res);
  },

  async createType(data: { name: string; label: string; description?: string; color?: string }): Promise<any> {
    const res = await fetch(`${BASE_URL}/types`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return handleResponse(res);
  },

  async updateType(name: string, data: { label?: string; description?: string; color?: string }): Promise<any> {
    const res = await fetch(`${BASE_URL}/types/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return handleResponse(res);
  },

  async deleteType(name: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/types/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    });
    return handleResponse(res);
  },

  // ── Links & Graph ───────────────────────────────────────────────
  async getLinks(): Promise<{ items: LinkItem[]; count: number }> {
    const res = await fetch(`${BASE_URL}/links`);
    const data = await handleResponse<any>(res);
    return {
      items: data.items || data.links || [],
      count: data.count ?? (data.items?.length || 0),
    };
  },

  async createLink(data: { from_id: string; to_id: string; rel: string }): Promise<LinkItem> {
    const res = await fetch(`${BASE_URL}/links`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return handleResponse<LinkItem>(res);
  },

  async deleteLink(params: { from_id: string; to_id: string; rel?: string }): Promise<{ ok: boolean }> {
    const query = new URLSearchParams({
      from_id: params.from_id,
      to_id: params.to_id,
    });
    if (params.rel) query.set('rel', params.rel);
    const res = await fetch(`${BASE_URL}/links?${query.toString()}`, {
      method: 'DELETE',
    });
    return handleResponse<{ ok: boolean }>(res);
  },

  async getGraph(): Promise<GraphData> {
    const res = await fetch(`${BASE_URL}/graph`);
    return handleResponse<GraphData>(res);
  },

  // ── Git Sync & Version Control ──────────────────────────────────
  async getGitStatus(): Promise<GitStatusInfo> {
    const res = await fetch(`${BASE_URL}/git/status`);
    return handleResponse<GitStatusInfo>(res);
  },

  async getGitHistory(limit = 30): Promise<{ commits: GitCommitItem[]; count: number }> {
    const res = await fetch(`${BASE_URL}/git/history?limit=${limit}`);
    return handleResponse(res);
  },

  async getGitDiff(params?: {
    path?: string;
    staged?: boolean;
    doc_id?: string;
  }): Promise<GitDiffResponse> {
    const query = new URLSearchParams();
    if (params?.path) query.set('path', params.path);
    if (params?.staged) query.set('staged', 'true');
    if (params?.doc_id) query.set('doc_id', params.doc_id);
    const qs = query.toString() ? `?${query.toString()}` : '';
    const res = await fetch(`${BASE_URL}/git/diff${qs}`);
    return handleResponse<GitDiffResponse>(res);
  },

  async gitCommit(message: string, full = false): Promise<any> {
    const res = await fetch(`${BASE_URL}/git/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, full }),
    });
    return handleResponse(res);
  },

  async gitPull(remote = 'origin', branch = 'main'): Promise<any> {
    const res = await fetch(`${BASE_URL}/git/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote, branch }),
    });
    return handleResponse(res);
  },

  async gitPush(remote = 'origin', branch = 'main'): Promise<any> {
    const res = await fetch(`${BASE_URL}/git/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remote, branch }),
    });
    return handleResponse(res);
  },

  async gitSync(message = 'sync: admin auto-commit'): Promise<any> {
    const res = await fetch(`${BASE_URL}/git/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    return handleResponse(res);
  },

  async gitInit(sync_dir?: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/git/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sync_dir }),
    });
    return handleResponse(res);
  },

  // ── Scheduler ───────────────────────────────────────────────────
  async getSchedulerStatus(): Promise<any> {
    const res = await fetch(`${BASE_URL}/scheduler/status`);
    return handleResponse(res);
  },

  async getSchedulerTasks(): Promise<{ tasks: SchedulerTaskItem[]; count: number }> {
    const res = await fetch(`${BASE_URL}/scheduler/tasks`);
    return handleResponse(res);
  },

  async getSchedulerHistory(limit = 50): Promise<{ history: SchedulerHistoryItem[]; count: number }> {
    const res = await fetch(`${BASE_URL}/scheduler/history?limit=${limit}`);
    return handleResponse(res);
  },

  async runSchedulerTask(taskName: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/scheduler/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_name: taskName }),
    });
    return handleResponse(res);
  },

  async enableSchedulerTask(taskName: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/scheduler/tasks/${encodeURIComponent(taskName)}/enable`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  async disableSchedulerTask(taskName: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/scheduler/tasks/${encodeURIComponent(taskName)}/disable`, {
      method: 'POST',
    });
    return handleResponse(res);
  },

  // ── Bulk Imports & Exports ──────────────────────────────────────
  async uploadImportZip(file: File, dryRun = false): Promise<any> {
    const formData = new FormData();
    formData.append('archive', file);
    formData.append('dry_run', String(dryRun));

    const res = await fetch(`${BASE_URL}/imports/upload`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(res);
  },

  getExportDownloadUrl(): string {
    return `${BASE_URL}/exports/download`;
  },

  // ── Config & Vaults ─────────────────────────────────────────────
  async getConfig(): Promise<{ ok: boolean; path: string; content: string }> {
    const res = await fetch(`${BASE_URL}/config`);
    return handleResponse(res);
  },

  async saveConfig(content: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    return handleResponse(res);
  },

  async getVaults(): Promise<{ current_vault: string; vaults: string[] }> {
    const res = await fetch(`${BASE_URL}/vaults`);
    const data = await handleResponse<any>(res);
    const current = data.current || data.current_vault || 'default';
    const list = Array.isArray(data.vaults)
      ? data.vaults.map((v: any) => (typeof v === 'string' ? v : v.name))
      : ['default'];
    return { current_vault: current, vaults: list };
  },

  async switchVault(name: string): Promise<{ ok: boolean; current_vault: string }> {
    const res = await fetch(`${BASE_URL}/vaults/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    return handleResponse(res);
  },
};
