import { Page, Locator, expect } from '@playwright/test';
import { smoothMove, slowClick, waitForPageReady, demoPause, PACING } from './demo-actions';

/**
 * Navigation helper for the School ERP application demo.
 * Simulates realistic user mouse interaction with the top navigation bar and dropdowns.
 */
export class DemoNavigation {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /**
   * Navigates to Dashboard (Cockpit).
   */
  async toDashboard(): Promise<void> {
    const link = this.page.locator('a.nav-item-link[href="/"], a.nav-item-link:has-text("Dashboard")').first();
    if (await link.isVisible()) {
      await slowClick(this.page, link, 'Navbar -> Dashboard');
    } else {
      await this.page.goto('/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Students Directory.
   */
  async toStudents(): Promise<void> {
    const link = this.page.locator('a.nav-item-link[href*="/students/"], a.nav-item-link:has-text("Élèves")').first();
    if (await link.isVisible()) {
      await slowClick(this.page, link, 'Navbar -> Élèves');
    } else {
      await this.page.goto('/students/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Cashier / Payments.
   */
  async toCashier(): Promise<void> {
    const link = this.page.locator('a.nav-item-link[href*="/cashier/"], a.nav-item-link:has-text("Caisse")').first();
    if (await link.isVisible()) {
      await slowClick(this.page, link, 'Navbar -> Caisse');
    } else {
      await this.page.goto('/cashier/payment/create/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Today's Sessions.
   */
  async toSessionsToday(): Promise<void> {
    const link = this.page.locator('a.nav-item-link[href*="/sessions/today/"], a.nav-item-link:has-text("Sessions du jour")').first();
    if (await link.isVisible()) {
      await slowClick(this.page, link, 'Navbar -> Sessions du jour');
    } else {
      await this.page.goto('/sessions/today/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Opens the Planning dropdown and navigates to the Weekly Schedule.
   */
  async toWeeklySchedule(): Promise<void> {
    const planningBtn = this.page.locator('button.nav-item-link:has-text("Planning")').first();
    if (await planningBtn.isVisible()) {
      await smoothMove(this.page, planningBtn);
      await planningBtn.click();
      await demoPause(this.page, PACING.MICRO);
      const weeklyLink = this.page.locator('a.nav-dropdown-item[href*="/schedule/"]:has-text("Planification hebdo")').first();
      await slowClick(this.page, weeklyLink, 'Planning Menu -> Hebdomadaire');
    } else {
      await this.page.goto('/schedule/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Opens the Pédagogie dropdown and navigates to Course Groups.
   */
  async toCourseGroups(): Promise<void> {
    const pedaBtn = this.page.locator('button.nav-item-link:has-text("Pédagogie")').first();
    if (await pedaBtn.isVisible()) {
      await smoothMove(this.page, pedaBtn);
      await pedaBtn.click();
      await demoPause(this.page, PACING.MICRO);
      const coursesLink = this.page.locator('a.nav-dropdown-item[href*="/courses/"]:has-text("Groupes de cours")').first();
      await slowClick(this.page, coursesLink, 'Pédagogie Menu -> Groupes de cours');
    } else {
      await this.page.goto('/courses/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Opens the Pédagogie dropdown and navigates to Teachers.
   */
  async toTeachers(): Promise<void> {
    const pedaBtn = this.page.locator('button.nav-item-link:has-text("Pédagogie")').first();
    if (await pedaBtn.isVisible()) {
      await smoothMove(this.page, pedaBtn);
      await pedaBtn.click();
      await demoPause(this.page, PACING.MICRO);
      const teachersLink = this.page.locator('a.nav-dropdown-item[href*="/teachers/"]:has-text("Professeurs")').first();
      await slowClick(this.page, teachersLink, 'Pédagogie Menu -> Professeurs');
    } else {
      await this.page.goto('/teachers/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Academic Levels.
   */
  async toLevels(): Promise<void> {
    const pedaBtn = this.page.locator('button.nav-item-link:has-text("Pédagogie")').first();
    if (await pedaBtn.isVisible()) {
      await smoothMove(this.page, pedaBtn);
      await pedaBtn.click();
      await demoPause(this.page, PACING.MICRO);
      const levelsLink = this.page.locator('a.nav-dropdown-item[href*="/levels/"]:has-text("Niveaux scolaires")').first();
      if (await levelsLink.isVisible()) {
        await slowClick(this.page, levelsLink, 'Pédagogie Menu -> Niveaux scolaires');
      } else {
        await this.page.goto('/levels/');
      }
    } else {
      await this.page.goto('/levels/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Rooms.
   */
  async toRooms(): Promise<void> {
    await this.page.goto('/rooms/');
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to Analytics Dashboard.
   */
  async toAnalytics(): Promise<void> {
    await this.page.goto('/analytics/dashboard/');
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to WhatsApp Center.
   */
  async toWhatsApp(): Promise<void> {
    const waLink = this.page.locator('a.nav-item-link[href*="/whatsapp/"], a#whatsappBtn').first();
    if (await waLink.isVisible()) {
      await slowClick(this.page, waLink, 'Navbar -> WhatsApp Hub');
    } else {
      await this.page.goto('/whatsapp/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }

  /**
   * Navigates to System Settings.
   */
  async toSettings(): Promise<void> {
    const settingsLink = this.page.locator('a.nav-item-link[href*="/settings/"], a.nav-item-link:has-text("Paramètres")').first();
    if (await settingsLink.isVisible()) {
      await slowClick(this.page, settingsLink, 'Navbar -> Paramètres');
    } else {
      await this.page.goto('/settings/');
    }
    await waitForPageReady(this.page);
    await demoPause(this.page, PACING.STANDARD);
  }
}
