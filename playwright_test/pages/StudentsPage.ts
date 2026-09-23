import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class StudentsPage extends BasePage {
  readonly searchInput: Locator;
  readonly studentRows: Locator;
  readonly addStudentBtn: Locator;
  readonly nameInput: Locator;
  readonly levelSelect: Locator;
  readonly phoneInput: Locator;
  readonly parentNameInput: Locator;
  readonly parentContactInput: Locator;
  readonly submitBtn: Locator;
  readonly deleteConfirmBtn: Locator;

  constructor(page: Page) {
    super(page);
    this.searchInput = page.locator('#search, input[name="q"], input[type="search"]').first();
    this.studentRows = page.locator('table tbody tr, .student-card');
    this.addStudentBtn = page.locator('a[href*="/students/create/"]').first();
    this.nameInput = page.locator('input[name="name"], #id_name');
    this.levelSelect = page.locator('select[name="level"], #id_level');
    this.phoneInput = page.locator('input[name="phone"], #id_phone');
    this.parentNameInput = page.locator('input[name="parent_name"], #id_parent_name');
    this.parentContactInput = page.locator('input[name="parent_contact"], #id_parent_contact');
    this.submitBtn = page.locator('button[type="submit"], input[type="submit"]');
    this.deleteConfirmBtn = page.locator('button[type="submit"], .btn-danger, input[type="submit"]');
  }

  async gotoList() {
    await this.page.goto('/students/', { waitUntil: 'domcontentloaded' });
  }

  async gotoCreate() {
    await this.page.goto('/students/create/', { waitUntil: 'domcontentloaded' });
  }

  async fillStudentForm(data: {
    name: string;
    levelIndex?: number;
    phone?: string;
    parentName?: string;
    parentContact: string;
  }) {
    await this.nameInput.fill(data.name);
    if (data.levelIndex !== undefined) {
      await this.levelSelect.selectOption({ index: data.levelIndex });
    } else {
      // Select first non-empty option
      const options = await this.levelSelect.locator('option').all();
      for (const opt of options) {
        const val = await opt.getAttribute('value');
        if (val) {
          await this.levelSelect.selectOption(val);
          break;
        }
      }
    }

    if (data.phone) await this.phoneInput.fill(data.phone);
    if (data.parentName) await this.parentNameInput.fill(data.parentName);
    await this.parentContactInput.fill(data.parentContact);
  }

  async submit() {
    await this.submitBtn.first().click();
  }

  async search(query: string) {
    if (await this.searchInput.isVisible()) {
      await this.searchInput.fill(query);
      await this.page.keyboard.press('Enter');
      await this.page.waitForLoadState('domcontentloaded');
    }
  }
}
