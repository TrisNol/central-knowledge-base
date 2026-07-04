import { Component, signal, inject } from '@angular/core';
import { Router, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs/operators';
import { ButtonModule } from 'primeng/button';
import { SidebarComponent } from '../sidebar/sidebar.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ButtonModule, SidebarComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly title = signal('frontend');
  protected readonly showSidebar = signal<boolean>(true);

  private readonly router = inject(Router);

  constructor() {
    // set initial visibility based on current URL
    const initialUrl = this.router.url || '/';
    this.showSidebar.set(initialUrl !== '/');

    // update on navigation
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((nav) => {
        this.showSidebar.set(nav.urlAfterRedirects !== '/');
      });
  }
}
