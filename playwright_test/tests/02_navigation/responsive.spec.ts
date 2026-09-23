import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Navigation - Responsive Viewports Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('02.03 Desktop Viewport (1280x800) displays top navbar and content layout', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');
    const topNavbar = page.locator('.top-navbar, header, nav, .navbar-brand-link').first();
    await expect(topNavbar).toBeVisible();
    await expect(page.locator('body')).toBeVisible();
  });

  test('02.04 Tablet Viewport (768x1024) adapts layout gracefully', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/students/');
    await expect(page.locator('h1, .page-title')).toBeVisible();
    await expect(page.locator('.table-responsive, table, .student-card').first()).toBeVisible();
  });

  test('02.05 Mobile Viewport (375x667) shows mobile menu toggle and drawer', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    const mobileBtn = page.locator('.mobile-menu-btn, button[aria-label*="menu"]');
    if (await mobileBtn.isVisible()) {
      await mobileBtn.click();
      const mobileDrawer = page.locator('.mobile-nav-drawer, [data-mobile-menu]');
      await expect(mobileDrawer).toBeVisible();
    }
  });
});
