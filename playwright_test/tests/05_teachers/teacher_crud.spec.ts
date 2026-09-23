import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Teachers - CRUD Operations Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('05.01 Should display teachers list with action buttons', async ({ teachersPage, page }) => {
    await teachersPage.gotoList();
    await expect(page).toHaveURL(/\/teachers\//);
    await expect(page.locator('.card, a[href*="/teachers/create/"]').first()).toBeVisible();
  });

  test('05.02 Should validate required teacher form fields', async ({ teachersPage, page }) => {
    await teachersPage.gotoCreate();
    await teachersPage.submit();
    await expect(page).toHaveURL(/\/teachers\/create\//);
  });

  test('05.03 Should successfully create a new teacher', async ({ teachersPage, page }) => {
    const timestamp = Date.now();
    const teacherName = `Prof. Test ${timestamp}`;

    await teachersPage.gotoCreate();
    await teachersPage.fillTeacherForm({
      name: teacherName,
      phone: '0611223344',
      email: `teacher.${timestamp}@test.com`,
    });
    await teachersPage.submit();
    await expect(page).not.toHaveURL(/\/teachers\/create\//);
  });

  test('05.04 Should view teacher detail page', async ({ page }) => {
    await page.goto('/teachers/1/');
    await expect(page).toHaveURL(/\/teachers\/1\//);
    await expect(page.locator('h1, .page-title, .teacher-avatar').first()).toBeVisible();
  });
});
