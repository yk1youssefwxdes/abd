import { test as baseTest, expect } from '@playwright/test';
import { BasePage } from '../pages/BasePage';
import { LoginPage } from '../pages/LoginPage';
import { CockpitPage } from '../pages/CockpitPage';
import { StudentsPage } from '../pages/StudentsPage';
import { TeachersPage } from '../pages/TeachersPage';
import { RoomsPage } from '../pages/RoomsPage';
import { CoursesPage } from '../pages/CoursesPage';
import { LevelsPage } from '../pages/LevelsPage';
import { SchedulePage } from '../pages/SchedulePage';
import { CashierPage } from '../pages/CashierPage';
import { WhatsAppPage } from '../pages/WhatsAppPage';
import { AnalyticsPage } from '../pages/AnalyticsPage';
import { PublicAttendancePage } from '../pages/PublicAttendancePage';
import { PublicKioskPage } from '../pages/PublicKioskPage';
import { SystemSettingsPage } from '../pages/SystemSettingsPage';

export interface AppFixtures {
  basePage: BasePage;
  loginPage: LoginPage;
  cockpitPage: CockpitPage;
  studentsPage: StudentsPage;
  teachersPage: TeachersPage;
  roomsPage: RoomsPage;
  coursesPage: CoursesPage;
  levelsPage: LevelsPage;
  schedulePage: SchedulePage;
  cashierPage: CashierPage;
  whatsappPage: WhatsAppPage;
  analyticsPage: AnalyticsPage;
  publicAttendancePage: PublicAttendancePage;
  publicKioskPage: PublicKioskPage;
  systemSettingsPage: SystemSettingsPage;
}

export const test = baseTest.extend<AppFixtures>({
  basePage: async ({ page }, use) => {
    await use(new BasePage(page));
  },
  loginPage: async ({ page }, use) => {
    await use(new LoginPage(page));
  },
  cockpitPage: async ({ page }, use) => {
    await use(new CockpitPage(page));
  },
  studentsPage: async ({ page }, use) => {
    await use(new StudentsPage(page));
  },
  teachersPage: async ({ page }, use) => {
    await use(new TeachersPage(page));
  },
  roomsPage: async ({ page }, use) => {
    await use(new RoomsPage(page));
  },
  coursesPage: async ({ page }, use) => {
    await use(new CoursesPage(page));
  },
  levelsPage: async ({ page }, use) => {
    await use(new LevelsPage(page));
  },
  schedulePage: async ({ page }, use) => {
    await use(new SchedulePage(page));
  },
  cashierPage: async ({ page }, use) => {
    await use(new CashierPage(page));
  },
  whatsappPage: async ({ page }, use) => {
    await use(new WhatsAppPage(page));
  },
  analyticsPage: async ({ page }, use) => {
    await use(new AnalyticsPage(page));
  },
  publicAttendancePage: async ({ page }, use) => {
    await use(new PublicAttendancePage(page));
  },
  publicKioskPage: async ({ page }, use) => {
    await use(new PublicKioskPage(page));
  },
  systemSettingsPage: async ({ page }, use) => {
    await use(new SystemSettingsPage(page));
  },
});

export { expect };
