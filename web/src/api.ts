const TOKEN_KEY = "cabina_api_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request(path: string, init: RequestInit = {}, token = getToken()): Promise<any> {
  const url = path.startsWith("/api") ? path : `/api${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...((init.headers as Record<string, string>) || {}),
  };
  const response = await fetch(url, { ...init, headers });
  if (response.status === 204) return null;
  const text = await response.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new Error(data?.error?.message || `HTTP ${response.status}`);
  }
  return data;
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, body?: unknown) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
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

export async function fetchBlob(path: string): Promise<string> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!response.ok) throw new Error(`media ${response.status}`);
  return URL.createObjectURL(await response.blob());
}
