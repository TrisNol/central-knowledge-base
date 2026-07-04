import { ChangeDetectionStrategy, Component, signal, inject, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ButtonModule } from 'primeng/button';
import { SettingsService, SettingsConfigResponse } from './settings.service';

interface ConfigSection {
  title: string;
  isDev?: boolean;
  items: Record<string, unknown>;
}

@Component({
  selector: 'app-settings',
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ButtonModule],
})
export class SettingsComponent {
  private readonly settings = inject(SettingsService);

  isWorking = signal(false);
  message = signal('');
  config = signal<Record<string, ConfigSection> | null>(null);
  configLoading = signal(false);
  configError = signal('');

  constructor() {
    effect(
      () => {
        this.loadConfig();
      },
      { allowSignalWrites: true },
    );
  }

  async loadConfig() {
    this.configLoading.set(true);
    this.configError.set('');
    try {
      const rawConfig: SettingsConfigResponse = await this.settings.getConfig();
      const sections: Record<string, ConfigSection> = {
        app: {
          title: 'Application',
          isDev: rawConfig.app?.environment === 'development',
          items: rawConfig.app || {},
        },
        auth: {
          title: 'Authentication',
          items: rawConfig.auth || {},
        },
        llm: {
          title: 'Language Model',
          items: rawConfig.llm || {},
        },
        embedding: {
          title: 'Embedding',
          items: rawConfig.embedding || {},
        },
        neo4j: {
          title: 'Graph Database',
          items: rawConfig.neo4j || {},
        },
        jira: {
          title: 'Jira Integration',
          items: { configured: rawConfig.jira?.configured },
        },
        confluence: {
          title: 'Confluence Integration',
          items: { configured: rawConfig.confluence?.configured },
        },
        github: {
          title: 'GitHub Integration',
          items: { configured: rawConfig.github?.configured },
        },
      };
      this.config.set(sections);
    } catch (err) {
      this.configError.set(err instanceof Error ? err.message : 'Failed to load config');
    } finally {
      this.configLoading.set(false);
    }
  }

  getSectionEntries(section: ConfigSection): [string, unknown][] {
    return Object.entries(section.items).filter(([, val]) => val !== null && val !== undefined);
  }

  formatValue(value: unknown): string {
    if (typeof value === 'boolean') {
      return value ? '✓ Yes' : '✗ No';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    return String(value);
  }

  async ingest() {
    if (this.isWorking()) return;
    this.isWorking.set(true);
    this.message.set('Ingesting documents...');
    try {
      const res = await this.settings.ingest();
      this.message.set(JSON.stringify(res));
    } catch (err) {
      this.message.set(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      this.isWorking.set(false);
    }
  }

  async clear() {
    if (this.isWorking()) return;
    this.isWorking.set(true);
    this.message.set('Clearing index...');
    try {
      const res = await this.settings.clear();
      this.message.set(JSON.stringify(res));
    } catch (err) {
      this.message.set(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      this.isWorking.set(false);
    }
  }
}
