import type { ApiErrorBody, HistoryResponse, LatestResponse, Location, SubscribePayload } from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!BASE_URL) {
    throw new Error("VITE_API_BASE_URL is not set. Copy .env.example to .env.local and fill it in.");
  }
  const res = await fetch(`${BASE_URL}${path}`, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (body as ApiErrorBody | null)?.error ?? `Request failed (${res.status})`;
    throw new Error(message);
  }
  return body as T;
}

export function getLocations(): Promise<{ locations: Location[] }> {
  return request("/locations");
}

export function getLatest(locationId: string): Promise<LatestResponse> {
  return request(`/pollen/${encodeURIComponent(locationId)}/latest`);
}

export function getHistory(locationId: string, days = 14): Promise<HistoryResponse> {
  return request(`/pollen/${encodeURIComponent(locationId)}/history?days=${days}`);
}

export function subscribe(payload: SubscribePayload): Promise<{ message: string }> {
  return request("/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
