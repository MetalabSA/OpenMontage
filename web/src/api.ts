const TOKEN_KEY = "cabina_api_token";
const CSRF_KEY = "cabina_csrf";
const USER_KEY = "cabina_user";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim());
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(CSRF_KEY);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}
export function getCsrf(): string {
  return localStorage.getItem(CSRF_KEY) || "";
}
export function getUser(): any {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}
export function setUser(user: any, csrf?: string): void {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (csrf) localStorage.setItem(CSRF_KEY, csrf);
}
export function clearSession(): void {
  localStorage.removeItem(CSRF_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

async function request(path: string, init: RequestInit = {}, token = getToken()): Promise<any> {
  const url = path.startsWith("/api") ? path : `/api${path}`;
  const method = (init.method || "GET").toUpperCase();
  const headers: Record<string, string> = {
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...((init.headers as Record<string, string>) || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!token && method !== "GET" && getCsrf()) headers["X-CSRF-Token"] = getCsrf();
  const response = await fetch(url, { ...init, headers, credentials: "include" });
  if (response.status === 204) return null;
  const text = await response.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  return data;
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, body?: unknown) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: (path: string, body?: unknown) => request(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  put: (path: string, body?: unknown) => request(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  del: (path: string) => request(path, { method: "DELETE" }),
};

export async function verifyToken(token: string): Promise<boolean> {
  try {
    await request("/api/auth/me", {}, token);
    return true;
  } catch {
    return false;
  }
}

export async function loginWithPassword(email: string, password: string): Promise<any> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error?.message || `HTTP ${response.status}`);
  clearToken();
  setUser(data.user, data.csrf_token);
  return data.user;
}

export async function fetchMe(): Promise<any | null> {
  try {
    const response = await fetch("/api/auth/me", { credentials: "include" });
    if (!response.ok) return null;
    const data = await response.json();
    setUser(data.user, data.csrf_token);
    return data.user;
  } catch {
    return null;
  }
}

export async function logoutSession(): Promise<void> {
  try {
    await request("/api/auth/logout", { method: "POST" }, "");
  } catch {
    /* ignore */
  }
  clearSession();
}

export async function fetchBlob(path: string): Promise<string> {
  const token = getToken();
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!response.ok) throw new Error(`media ${response.status}`);
  return URL.createObjectURL(await response.blob());
}
