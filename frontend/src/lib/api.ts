const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

import { authHeaders, clearAuth, getToken, setAuth, type AuthUser, type UserProfile } from '$lib/auth';

export type { AuthUser, UserProfile };
export { clearAuth, getToken, setAuth, getStoredUser, isLoggedIn } from '$lib/auth';

export type Preset = 'fast' | 'balanced' | 'quality';

export interface VideoInfo {
  video_id: string;
  filename: string;
  duration_sec?: number;
  fps?: number;
  frame_count?: number;
  width?: number;
  height?: number;
}

export interface ParseResponse {
  operation: string;
  summary: string;
  parameters: Record<string, unknown>;
  supported: boolean;
  warnings: string[];
  metadata: Record<string, unknown>;
  needs_clarification: boolean;
  clarification_question?: string;
  validation?: { ok: boolean; errors?: string[]; missing?: string[] };
  tier?: 'default' | 'premium';
  premium_required?: boolean;
  executable_default?: boolean;
  user_message?: string;
  premium_message?: string | null;
}

export interface JobStatus {
  job_id: string;
  state: 'queued' | 'running' | 'done' | 'error';
  stage: string;
  progress: number;
  message: string;
  operation?: string;
  summary?: string;
  plan?: ParseResponse;
  output_video_path?: string;
  error?: string;
  error_code?: string;
  validation?: Record<string, unknown>;
  artifacts?: Record<string, unknown>;
  premium_required?: boolean;
  premium_message?: string | null;
}

export interface SystemStatus {
  parser: {
    ollama_available: boolean;
    ollama_model: string;
    warnings: string[];
  };
  hardware: Record<string, unknown>;
  recommended_preset: Preset;
  presets: Preset[];
  default_features?: string[];
  premium_features?: string[];
  dev_premium_unlocked?: boolean;
}

function formatApiError(body: Record<string, unknown>, status: number, path: string): string {
  const detail = body.detail ?? body.error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) return String(item.msg);
        return JSON.stringify(item);
      })
      .join('; ');
  }
  if (status === 404 && path.startsWith('/api/auth')) {
    return 'Auth API not found — restart the backend (py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000)';
  }
  return `Request failed (${status})`;
}

/** Login/register 401 = bad credentials — must not trigger session-expired redirect. */
const AUTH_CREDENTIAL_PATHS = new Set(['/api/auth/login', '/api/auth/register']);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    ...authHeaders(),
    ...(init?.headers as Record<string, string> | undefined)
  };
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new Error(
      `Cannot reach the API at ${API_BASE}. Start the backend: py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000`
    );
  }
  if (res.status === 401 && !AUTH_CREDENTIAL_PATHS.has(path)) {
    clearAuth();
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new Error('Session expired — please log in again');
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error(formatApiError(body, res.status, path));
  }
  return res.json();
}

export async function checkAuthApi(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/ping`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  return request('/api/system/status');
}

export async function uploadVideo(file: File): Promise<VideoInfo> {
  const form = new FormData();
  form.append('file', file);
  return request('/api/videos/upload', { method: 'POST', body: form });
}

export function videoStreamUrl(videoId: string): string {
  return `${API_BASE}/api/videos/${videoId}/stream`;
}

export function jobVideoUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/video`;
}

/** Trigger a browser download of the edited MP4 (not just open in a new tab). */
export async function downloadJobVideo(jobId: string, filename = 'aiedit_export.mp4') {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/video`, { headers: authHeaders() });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error(String(body.detail ?? body.error ?? `Download failed (${res.status})`));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function parsePrompt(prompt: string): Promise<ParseResponse> {
  return request('/api/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ prompt })
  });
}

export async function submitJob(
  prompt: string,
  videoId: string,
  preset: Preset,
  referenceIds: string[] = [],
  usePremium = false
): Promise<JobStatus> {
  return request('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      prompt,
      video_id: videoId,
      preset,
      reference_ids: referenceIds,
      use_premium: usePremium
    })
  });
}

export async function getJob(jobId: string): Promise<JobStatus> {
  return request(`/api/jobs/${jobId}`);
}

export async function uploadReference(file: File): Promise<{ ref_id: string; filename: string }> {
  const form = new FormData();
  form.append('file', file);
  return request('/api/references/upload', { method: 'POST', body: form });
}

export function formatDuration(sec?: number): string {
  if (!sec || sec <= 0) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function operationLabel(op?: string): string {
  const labels: Record<string, string> = {
    text_replacement: 'Text Replacement',
    text_removal: 'Text Removal',
    text_detection: 'Text Detection',
    frame_extraction: 'Frame Extraction',
    character_hair_recolor: 'Hair Recolor',
    object_recolor: 'Object Recolor',
    object_remove: 'Object Remove',
    object_replace_guided: 'Object Replace',
    global_color_change: 'Global Color Change',
    atmosphere_overlay: 'Atmosphere Overlay',
    auto_commentary: 'Auto Commentary',
    timeline_trim: 'Trim / Cut',
    speed_change: 'Speed Change',
    crop_resize: 'Crop / Resize',
    volume_adjust: 'Volume / Audio',
    fade_in_out: 'Fade In/Out',
    rotate_flip: 'Rotate / Flip',
    brightness_contrast: 'Brightness / Contrast',
    timeline_edit: 'Timeline Montage',
    codegen_edit: 'Premium Custom Edit',
    unsupported: 'Unsupported'
  };
  return labels[op ?? ''] ?? op ?? '—';
}

// ——— Auth & billing ———

export async function authRegister(email: string, password: string, displayName: string) {
  return request<{ token: string; user: AuthUser }>('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName })
  });
}

export async function authLogin(email: string, password: string) {
  return request<{ token: string; user: AuthUser }>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
}

export async function authLogout() {
  try {
    await request('/api/auth/logout', { method: 'POST' });
  } finally {
    clearAuth();
  }
}

export async function fetchProfile(): Promise<UserProfile> {
  return request('/api/auth/profile');
}

export async function subscribePlan(plan: 'normal' | 'premium'): Promise<UserProfile> {
  return request('/api/auth/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ plan })
  });
}

export async function upgradeToPremium(): Promise<UserProfile> {
  return request('/api/auth/upgrade/premium', { method: 'POST' });
}

export async function boostPremium50(): Promise<UserProfile> {
  return request('/api/auth/boost/50', { method: 'POST' });
}

export async function renewPlan(keepBoosted: boolean): Promise<UserProfile> {
  return request('/api/auth/renew', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ keep_boosted: keepBoosted })
  });
}

export async function revertBoost(): Promise<UserProfile> {
  return request('/api/auth/revert-boost', { method: 'POST' });
}
