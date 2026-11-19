const TOKEN_KEY = 'aiedit_token';
const USER_KEY = 'aiedit_user';

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface UserProfile {
  user_id: string;
  email: string;
  display_name: string;
  subscription_status: 'none' | 'active' | 'expired';
  plan: {
    kind: 'normal' | 'premium' | null;
    name: string | null;
    weekly_price_inr: number;
    daily_edit_limit: number;
    codegen_enabled: boolean;
    boost_count: number;
    base_plan_kind: string | null;
    base_weekly_price_inr: number;
    base_daily_limit: number;
    week_started_at: string | null;
    week_ends_at: string | null;
  };
  usage: {
    edits_today: number;
    edits_remaining_today: number;
    limit_reached: boolean;
  };
  permissions: {
    can_edit: boolean;
    codegen_enabled: boolean;
  };
  pricing_inr?: { normal_weekly: number; premium_weekly: number };
  payments?: Array<{ amount_inr: number; payment_type: string; created_at: string; note?: string }>;
  offers?: Record<string, unknown>;
}

export function getToken(): string | null {
  if (typeof localStorage === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser(): AuthUser | null {
  if (typeof localStorage === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function isLoggedIn(): boolean {
  return !!getToken();
}
