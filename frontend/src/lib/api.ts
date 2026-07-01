import { getApiKey } from "./auth";

const BASE_URL = "http://localhost:8090";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const key = getApiKey();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (key) {
    headers["Authorization"] = `Bearer ${key}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined });
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}
