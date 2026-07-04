import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChatService, ChatMessage, ProviderStatus, ChatMode, MCPAuthType } from './chat.service';
import { MarkdownComponent } from 'ngx-markdown';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { PopoverModule } from 'primeng/popover';

@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
  imports: [FormsModule, MarkdownComponent, MultiSelectModule, SelectModule, PopoverModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatComponent {
  private readonly chat = inject(ChatService);

  // UI state signals
  input = signal('');
  isThinking = signal(false);
  messages = signal<ChatMessage[]>([]);
  providerStatus = signal<Record<ProviderStatus['provider'], boolean>>({
    github: false,
    atlassian: false,
  });
  providerConnectionType = signal<
    Record<ProviderStatus['provider'], 'oauth' | 'fallback' | 'none'>
  >({
    github: 'none',
    atlassian: 'none',
  });

  // Chat mode selection
  chatMode = signal<ChatMode>('mcp');
  mcpAuthType = signal<MCPAuthType>('oauth');

  // Sources multi-select (settings) - allows multiple selections
  selectedSources: string[] = ['JIRA', 'CONFLUENCE', 'GITHUB'];
  // Multi-select options for knowledge sources
  sourceOptions = [
    { label: 'Jira', value: 'JIRA' },
    { label: 'Confluence', value: 'CONFLUENCE' },
    { label: 'GitHub', value: 'GITHUB' },
  ];

  // Single-select options for chat mode
  chatModeOptions = [
    { label: 'RAG (Knowledge Base)', value: 'rag' as ChatMode },
    { label: 'MCP (External Tools)', value: 'mcp' as ChatMode },
  ];

  // Single-select options for MCP authentication
  mcpAuthTypeOptions = [
    { label: 'OAuth', value: 'oauth' as MCPAuthType },
    { label: 'Service Credentials', value: 'service_credentials' as MCPAuthType },
  ];

  // Auto-scroll effect on new messages
  constructor() {
    effect(() => {
      // access messages to create dependency
      this.messages();
      queueMicrotask(() => {
        const el = document.querySelector('.chat__messages');
        if (el) el.scrollTop = el.scrollHeight;
      });
    });

    // Load chat history on initialization
    this.loadChatHistory();
    this.loadProviderStatus();
    this.reportOAuthCallbackStatus();
  }

  private reportOAuthCallbackStatus() {
    const params = new URLSearchParams(window.location.search);
    const status = params.get('status');
    const provider = params.get('provider');
    const error = params.get('error');
    if (status === 'error' && provider && error) {
      console.error(`[OAuth ${provider}] ${error}`);
    }
  }

  private async loadProviderStatus() {
    const status = await this.chat.getAuthStatus();
    const nextState: Record<ProviderStatus['provider'], boolean> = {
      github: false,
      atlassian: false,
    };
    const nextConnectionType: Record<ProviderStatus['provider'], 'oauth' | 'fallback' | 'none'> = {
      github: 'none',
      atlassian: 'none',
    };
    for (const item of status) {
      nextState[item.provider] = item.connected;
      nextConnectionType[item.provider] = item.connection_type ?? 'none';
    }
    this.providerStatus.set(nextState);
    this.providerConnectionType.set(nextConnectionType);
  }

  private async loadChatHistory() {
    try {
      const history = await this.chat.getChatHistory();
      if (history.length > 0) {
        this.messages.set(history);
      }
    } catch (err) {
      console.error('Failed to load chat history:', err);
    }
  }

  async clearHistory() {
    try {
      await this.chat.clearChatHistory();
      this.messages.set([]);
    } catch (err) {
      console.error('Failed to clear chat history:', err);
    }
  }

  connectProvider(provider: ProviderStatus['provider']) {
    const mode = this.providerConnectionType()[provider] === 'fallback' ? 'oauth' : undefined;
    this.chat.connectProvider(provider, mode);
  }

  shouldDisconnect(provider: ProviderStatus['provider']): boolean {
    return (
      this.providerStatus()[provider] && this.providerConnectionType()[provider] !== 'fallback'
    );
  }

  async disconnectProvider(provider: ProviderStatus['provider']) {
    const ok = await this.chat.disconnectProvider(provider);
    if (ok) {
      await this.loadProviderStatus();
    }
  }

  // Note: Popover (OverlayPanel) is toggled from template using a template reference variable

  async send() {
    const text = this.input().trim();
    if (!text || this.isThinking()) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      createdAt: new Date(),
    };
    this.messages.update((arr) => [...arr, userMsg]);
    this.input.set('');

    this.isThinking.set(true);
    try {
      const ans = await this.chat.ask(
        text,
        this.selectedSources,
        this.chatMode(),
        this.mcpAuthType(),
      );
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: ans.content,
        refs: ans.refs,
        createdAt: new Date(),
      };
      this.messages.update((arr) => [...arr, assistantMsg]);
    } finally {
      this.isThinking.set(false);
    }
  }
}
