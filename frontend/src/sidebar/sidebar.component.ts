import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

@Component({
  selector: 'app-sidebar',
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
  host: {
    '[class.collapsed]': 'collapsed',
  },
})
export class SidebarComponent {
  collapsed = false;
  items = [
    { label: 'Chat', icon: 'pi pi-comments', route: '/chat' },
    { label: 'Knowledge Graph', icon: 'pi pi-sitemap', route: '/graph' },
    { label: 'Settings', icon: 'pi pi-cog', route: '/settings' },
  ];

  toggleCollapse() {
    this.collapsed = !this.collapsed;
  }
}
