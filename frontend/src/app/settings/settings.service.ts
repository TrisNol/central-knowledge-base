import { Injectable } from '@angular/core';

export interface SettingsConfigResponse {
  app?: {
    environment?: string;
    [key: string]: unknown;
  };
  auth?: Record<string, unknown>;
  llm?: Record<string, unknown>;
  embedding?: Record<string, unknown>;
  neo4j?: Record<string, unknown>;
  jira?: {
    configured?: boolean;
    [key: string]: unknown;
  };
  confluence?: {
    configured?: boolean;
    [key: string]: unknown;
  };
  github?: {
    configured?: boolean;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export type SettingsActionResponse = Record<string, unknown>;

@Injectable({ providedIn: 'root' })
export class SettingsService {
  // Optionally override by setting (window as any).__API_URL__
  private readonly apiBase: string = 'http://localhost:8000';

  async getConfig(): Promise<SettingsConfigResponse> {
    const url = `${this.apiBase}/config`;
    const res = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'include',
    });
    if (!res.ok) throw new Error(`Config request failed with status ${res.status}`);
    return (await res.json()) as SettingsConfigResponse;
  }

  async ingest(): Promise<SettingsActionResponse> {
    const url = `${this.apiBase}/index/create`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'include',
    });
    if (!res.ok) throw new Error(`Ingest request failed with status ${res.status}`);
    try {
      return (await res.json()) as SettingsActionResponse;
    } catch {
      return { status: 'ok' };
    }
  }

  async clear(): Promise<SettingsActionResponse> {
    const url = `${this.apiBase}/index/clear`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'include',
    });
    if (!res.ok) throw new Error(`Clear request failed with status ${res.status}`);
    try {
      return (await res.json()) as SettingsActionResponse;
    } catch {
      return { status: 'ok' };
    }
  }
}
