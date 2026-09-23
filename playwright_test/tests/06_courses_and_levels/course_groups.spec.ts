import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Courses & Course Groups Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('06.01 Should display course groups list with cards and filters', async ({ coursesPage }) => {
    await coursesPage.gotoList();
    await expect(coursesPage.groupRows.first()).toBeVisible();
  });

  test('06.02 Should validate required fields when creating a course group', async ({ coursesPage, page }) => {
    await coursesPage.gotoCreate();
    await coursesPage.submit();
    await expect(page).toHaveURL(/\/courses\/create\//);
  });

  test('06.03 Should view course group detail page', async ({ page }) => {
    await page.goto('/courses/');
    const firstCourseLink = page.locator('table tbody tr a, .course-card a').first();
    await firstCourseLink.click();
    await expect(page).toHaveURL(/\/courses\/\d+/);
    await expect(page.locator('h1, .page-title')).toBeVisible();
  });
});
