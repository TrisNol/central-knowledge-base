import { Injectable } from '@angular/core';
import { environment } from '../../environments/environment';

export type DocumentSourceType = 'JIRA' | 'CONFLUENCE' | 'GITHUB';

interface BaseMetadata {
  source: string;
  type: DocumentSourceType;
  last_updated: string;
}

interface JiraMetadata extends BaseMetadata {
  type: 'JIRA';
  issue_key: string;
  project_key: string;
  title: string;
}

interface ConfluenceMetadata extends BaseMetadata {
  type: 'CONFLUENCE';
  page_id: string;
  space_key: string;
  title: string;
}

interface GitHubMetadata extends BaseMetadata {
  type: 'GITHUB';
  repo_name: string;
  file_path: string;
  commit_hash: string;
  ref: string;
}

export type GraphNodeMetadata = JiraMetadata | ConfluenceMetadata | GitHubMetadata;

export interface GraphNode {
  id: string;
  title: string;
  url: string;
  type: DocumentSourceType;
  metadata: GraphNodeMetadata;
  iconUrl?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

@Injectable({ providedIn: 'root' })
export class KnowledgeGraphService {
  private readonly apiBase = environment.apiBase;

  async fetchGraph(limit = 100): Promise<GraphResponse> {
    const url = `${this.apiBase}/graph?limit=${limit}`;

    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
      }

      const data = (await res.json()) as GraphResponse;

      // Add iconUrl to each node
      data.nodes = data.nodes.map((node) => ({
        ...node,
        iconUrl: `${this.apiBase}/icon?type=${encodeURIComponent(node.type)}`,
      }));

      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('Failed to fetch knowledge graph:', message);
      return { nodes: [], edges: [] };
    }
  }

  async fetchGraphStats(): Promise<{ relationships: Record<string, number> }> {
    const url = `${this.apiBase}/graph/stats`;

    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
      }

      return await res.json();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('Failed to fetch graph stats:', message);
      return { relationships: {} };
    }
  }

  async fetchDocumentRelationships(docId: string, depth = 1): Promise<GraphResponse> {
    const url = `${this.apiBase}/graph/document/${encodeURIComponent(docId)}?depth=${depth}`;

    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
      }

      const data = (await res.json()) as GraphResponse;

      // Add iconUrl to each node
      data.nodes = data.nodes.map((node) => ({
        ...node,
        iconUrl: `${this.apiBase}/icon?type=${encodeURIComponent(node.type)}`,
      }));

      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('Failed to fetch document relationships:', message);
      return { nodes: [], edges: [] };
    }
  }
}
