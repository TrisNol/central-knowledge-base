import { Component, signal, inject, OnInit } from '@angular/core';
import { FFlowModule } from '@foblex/flow';
import { KnowledgeGraphService, GraphNode, GraphEdge } from './knowledge-graph.service';
import { NodeComponent } from './components/node/node.component';

@Component({
  selector: 'app-knowledge-graph',
  templateUrl: './knowledge-graph.component.html',
  styleUrls: ['./knowledge-graph.component.scss'],
  imports: [FFlowModule, NodeComponent],
})
export class KnowledgeGraphComponent implements OnInit {
  private readonly graphService = inject(KnowledgeGraphService);

  nodes = signal<GraphNode[]>([]);
  edges = signal<GraphEdge[]>([]);
  isLoading = signal(false);
  stats = signal<Record<string, number>>({});
  totalNodes = signal(0);
  totalEdges = signal(0);

  async ngOnInit() {
    await this.loadGraph();
    await this.loadStats();
  }

  async loadGraph() {
    this.isLoading.set(true);
    try {
      const data = await this.graphService.fetchGraph(100);
      console.log('Loaded graph data:', {
        nodeCount: data.nodes.length,
        edgeCount: data.edges.length,
        nodes: data.nodes.map((n) => ({ id: n.id, title: n.title })),
        edges: data.edges,
      });
      this.nodes.set(data.nodes);
      this.edges.set(data.edges);
      this.totalNodes.set(data.nodes.length);
      this.totalEdges.set(data.edges.length);
    } finally {
      this.isLoading.set(false);
    }
  }

  async loadStats() {
    try {
      const data = await this.graphService.fetchGraphStats();
      this.stats.set(data.relationships);
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  }

  getNodePosition(index: number): { x: number; y: number } {
    // Improved layout: arrange nodes in a grid with better spacing
    const cols = 5;
    const spacing = 300;
    const row = Math.floor(index / cols);
    const col = index % cols;
    return {
      x: 100 + col * spacing,
      y: 100 + row * spacing,
    };
  }

  getStatsEntries(): { label: string; count: number }[] {
    const stats = this.stats();
    return Object.entries(stats).map(([key, count]) => ({
      label: key.replace(/_/g, ' → ').replace(/to/g, ''),
      count,
    }));
  }
}
