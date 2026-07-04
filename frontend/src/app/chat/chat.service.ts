import { Injectable } from '@angular/core';
import { environment } from '../../environments/environment';

export type ChatRole = 'user' | 'assistant';

export type ChatMode = 'rag' | 'mcp';
export type MCPAuthType = 'oauth' | 'service_credentials';

export interface ChatReference {
  title: string;
  url: string;
  /**
   * Legacy/simple icon hint used for CSS fallbacks. Prefer `iconUrl` when available.
   */
  icon?: 'link' | 'doc' | 'code';
  /**
   * Optional URL to an icon image served by the API (e.g. `/icon?type=JIRA`).
   * When present the UI should render the image.
   */
  iconUrl?: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  refs?: ChatReference[];
  createdAt: Date;
}

export interface ChatHistoryResponse {
  session_id: string;
  messages: {
    role: string;
    content: string;
    timestamp: string;
    sources?: {
      source?: string;
      type: 'JIRA' | 'CONFLUENCE' | 'GITHUB';
      last_updated?: string;
      title?: string;
      issue_key?: string;
      project_key?: string;
      page_id?: string;
      space_key?: string;
      repo_name?: string;
      file_path?: string;
      commit_hash?: string;
      ref?: string;
    }[];
  }[];
}

export interface ProviderStatus {
  provider: 'github' | 'atlassian';
  connected: boolean;
  connection_type?: 'oauth' | 'fallback' | 'none';
  expires_at?: string | null;
  scope?: string | null;
}

export interface AuthMeResponse {
  session_id: string;
  providers: ProviderStatus[];
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  // Optionally allow overriding the API base URL by setting (window as any).__API_URL__ = 'http://localhost:8000'
  private readonly apiBase = environment.apiBase;

  async getChatHistory(): Promise<ChatMessage[]> {
    const url = `${this.apiBase}/chat/history`;

    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        console.warn(`Failed to fetch chat history: ${res.status}`);
        return [];
      }

      const data = (await res.json()) as ChatHistoryResponse;

      // Convert backend format to frontend ChatMessage format
      return data.messages.map((msg) => {
        const message: ChatMessage = {
          id: crypto.randomUUID(),
          role: msg.role as ChatRole,
          content: msg.content,
          createdAt: new Date(msg.timestamp),
        };

        // Convert sources to refs if present
        if (msg.sources && msg.sources.length > 0) {
          message.refs = msg.sources.map((doc): ChatReference => {
            const icon: ChatReference['icon'] =
              doc.type === 'GITHUB' ? 'code' : doc.type === 'CONFLUENCE' ? 'doc' : 'link';
            const iconUrl = `${this.apiBase}/icon?type=${encodeURIComponent(doc.type)}`;

            // Prefer backend-provided link in `source`, otherwise try to construct a sensible fallback
            let url = doc.source || '';
            if (!url && doc.type === 'GITHUB' && doc.repo_name && doc.file_path) {
              const ref = doc.ref || 'main';
              url = `https://github.com/${doc.repo_name}/blob/${encodeURIComponent(ref)}/${doc.file_path}`;
            }

            let title: string;
            switch (doc.type) {
              case 'JIRA':
                title = doc.issue_key ?? 'Jira';
                break;
              case 'CONFLUENCE':
                if (doc.space_key && doc.title) {
                  title = `${doc.space_key}: ${doc.title}`;
                } else {
                  title = 'Confluence';
                }
                break;
              case 'GITHUB':
                if (doc.repo_name && doc.file_path) {
                  title = `${doc.repo_name}/${doc.file_path}`;
                } else {
                  title = 'GitHub';
                }
                break;
              default:
                title = doc.type ?? 'Document';
            }

            return { title, url: url || '#', icon, iconUrl };
          });
        }

        return message;
      });
    } catch (err) {
      console.error('Error fetching chat history:', err);
      return [];
    }
  }

  async clearChatHistory(): Promise<void> {
    const url = `${this.apiBase}/chat/clear`;

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        console.warn(`Failed to clear chat history: ${res.status}`);
      }
    } catch (err) {
      console.error('Error clearing chat history:', err);
    }
  }

  async getAuthStatus(): Promise<ProviderStatus[]> {
    const url = `${this.apiBase}/auth/me`;

    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });

      if (!res.ok) {
        console.warn(`Failed to fetch auth status: ${res.status}`);
        return [];
      }

      const data = (await res.json()) as AuthMeResponse;
      return data.providers ?? [];
    } catch (err) {
      console.error('Error fetching auth status:', err);
      return [];
    }
  }

  connectProvider(provider: ProviderStatus['provider'], mode?: 'oauth'): void {
    const query = mode ? `?mode=${encodeURIComponent(mode)}` : '';
    const connectUrl = `${this.apiBase}/auth/${provider}/connect${query}`;
    window.location.assign(connectUrl);
  }

  async disconnectProvider(provider: ProviderStatus['provider']): Promise<boolean> {
    const url = `${this.apiBase}/auth/${provider}/disconnect`;

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
        },
        credentials: 'include',
      });
      return res.ok;
    } catch (err) {
      console.error(`Error disconnecting provider ${provider}:`, err);
      return false;
    }
  }

  async ask(
    prompt: string,
    sources: string[],
    chatMode: ChatMode = 'mcp',
    mcpAuthType: MCPAuthType = 'oauth',
  ): Promise<Omit<ChatMessage, 'id' | 'role' | 'createdAt'>> {
    const url = `${this.apiBase}/ask`;

    try {
      const payload = {
        question: prompt,
        sources,
        chat_mode: chatMode,
        mcp_auth_type: mcpAuthType,
      };

      const res = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
      }

      type DocumentSourceType = 'JIRA' | 'CONFLUENCE' | 'GITHUB';
      interface BaseMetadata {
        source?: string;
        title?: string;
        type: DocumentSourceType;
        last_updated?: string;
        issue_key?: string;
        project_key?: string;
        page_id?: string;
        space_key?: string;
        repo_name?: string;
        file_path?: string;
        commit_hash?: string;
        ref?: string;
      }
      interface ResponseModel {
        answer: string;
        source_documents: BaseMetadata[];
      }

      const data = (await res.json()) as ResponseModel;

      const refs: ChatReference[] = (data.source_documents ?? []).map((doc): ChatReference => {
        const icon: ChatReference['icon'] =
          doc.type === 'GITHUB' ? 'code' : doc.type === 'CONFLUENCE' ? 'doc' : 'link';
        const iconUrl = `${this.apiBase}/icon?type=${encodeURIComponent(doc.type)}`;

        let url = doc.source || '';
        if (!url && doc.type === 'GITHUB' && doc.repo_name && doc.file_path) {
          const ref = doc.ref || 'main';
          url = `https://github.com/${doc.repo_name}/blob/${encodeURIComponent(ref)}/${doc.file_path}`;
        }

        let title: string;
        switch (doc.type) {
          case 'JIRA':
            title = doc.issue_key ?? 'Jira';
            break;
          case 'CONFLUENCE':
            if (doc.space_key && doc.title) {
              title = `${doc.space_key}: ${doc.title}`;
            } else {
              title = 'Confluence';
            }
            break;
          case 'GITHUB':
            if (doc.repo_name && doc.file_path) {
              title = `${doc.repo_name}/${doc.file_path}`;
            } else {
              title = 'GitHub';
            }
            break;
          default:
            title = doc.type ?? 'Document';
        }
        return { title, url: url || '#', icon, iconUrl };
      });

      return { content: data.answer, refs };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      return {
        content: `Sorry, I couldn't get an answer from the server. ${message}`,
        refs: [],
      };
    }
  }
}
