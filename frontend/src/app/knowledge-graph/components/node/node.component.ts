import { Component, input } from '@angular/core';
import { FFlowModule } from '@foblex/flow';
import { ButtonModule } from 'primeng/button';

@Component({
  selector: 'app-knowledge-graph-node',
  templateUrl: './node.component.html',
  styleUrls: ['./node.component.scss'],
  imports: [ButtonModule, FFlowModule],
})
export class NodeComponent {
  title = input.required<string>();
  url = input.required<string>();
  iconUrl = input<string>();
}
