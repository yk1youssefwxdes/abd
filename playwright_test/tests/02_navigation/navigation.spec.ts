import { test, expect } from '../../fixtures/base.fixture';
import { loginAsAdmin } from '../../fixtures/auth.fixture';

test.describe('Navigation - Navbar and Links Suite', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('02.01 Should navigate smoothly across all main navbar modules', async ({ page }) => {
    const navModules = [
      { name: 'Dashboard', url: '/' },
      { name: 'Élèves', url: '/students/' },
      { name: 'Groupes', url: '/courses/' },
      { name: 'Emploi du temps', url: '/schedule/' },
      { name: 'Caisse', url: '/cashier/payment/create/' },
      { name: 'WhatsApp', url: '/whatsapp/' },
      { name: 'Enseignants', url: '/teachers/' },
      { name: 'Salles', url: '/rooms/' },
      { name: 'Niveaux', url: '/levels/' },
      { name: 'Analytics', url: '/analytics/dashboard/' },
      { name: 'Paramètres', url: '/settings/' },
    ];

    for (const mod of navModules) {
      await page.goto(mod.url);
      await expect(page).toHaveURL(new RegExp(mod.url));
      await expect(page.locator('body')).toBeVisible();
    }
  });

  test('02.02 Should return 404 page for non-existent routes', async ({ page }) => {
    const response = await page.goto('/this-route-does-not-exist-404/');
    expect(response?.status()).toBe(404);
  });
});
