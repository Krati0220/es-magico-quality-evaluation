import type {
  HealthResponse,
  OverviewResponse,
  PlaygroundResponse,
  ReviewResponse,
  RunDetail,
  RunSummary,
} from './types';

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');

let accessToken = localStorage.getItem('es_eval_token') || '';

export function getStoredToken(): string {
  return accessToken;
}

export function setStoredToken(token: string): void {
  accessToken = token.trim();
  if (accessToken) {
    localStorage.setItem('es_eval_token', accessToken);
  } else {
    localStorage.removeItem('es_eval_token');
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (accessToken) {
    headers.set('X-Access-Token', accessToken);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      // ignore non-JSON body
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  overview: () => request<OverviewResponse>('/api/overview'),
  playgroundRun: (payload: {
    case_id?: string | null;
    custom_conversation?: string | null;
    versions: string[];
    custom_prompt?: string | null;
    run_judge: boolean;
    use_mock: boolean;
    temperature?: number;
  }) =>
    request<PlaygroundResponse>('/api/playground/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listRuns: () => request<{ runs: RunSummary[] }>('/api/runs'),
  createRun: (payload: {
    name?: string;
    scope: 'smoke' | 'full';
    candidate_version: 'v2' | 'v3';
    use_mock: boolean;
    rate_limit_delay?: number;
    repeats?: number;
  }) =>
    request<{ run_id: string; status: string }>('/api/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getRun: (runId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  resumeRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/api/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
    }),
  cancelRun: (runId: string) =>
    request<{ run_id: string; cancel_requested: boolean }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),
  getReview: (runId: string) => request<ReviewResponse>(`/api/runs/${encodeURIComponent(runId)}/review`),
  submitReview: (
    runId: string,
    reviewId: string,
    payload: {
      reviewed_by: string;
      human_attestation: boolean;
      faithfulness: number;
      completeness: number;
      usefulness: number;
      critical_errors: string[];
      notes: string;
    },
  ) =>
    request<{ saved: boolean; review_id: string; recommendation: string }>(
      `/api/runs/${encodeURIComponent(runId)}/review/${encodeURIComponent(reviewId)}`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  exportRun: (runId: string) => request<Record<string, unknown>>(`/api/runs/${encodeURIComponent(runId)}/export`),
  saveDeliverables: (runId: string) =>
    request<{ saved: boolean; directory: string; files_written: string[] }>(
      `/api/runs/${encodeURIComponent(runId)}/save-deliverables`,
      { method: 'POST' },
    ),
};
