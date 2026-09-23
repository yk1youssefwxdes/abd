import { Page, Locator, expect } from '@playwright/test';

/**
 * Pacing configuration in milliseconds.
 * Can be scaled via DEMO_SPEED environment variable (e.g. 1.0 = normal, 0.5 = fast, 1.5 = slower)
 */
const SPEED_FACTOR = parseFloat(process.env.DEMO_SPEED || '1.0');

export const PACING = {
  MICRO: Math.round(400 * SPEED_FACTOR),
  STANDARD: Math.round(1100 * SPEED_FACTOR),
  READING: Math.round(1800 * SPEED_FACTOR),
  SECTION: Math.round(2400 * SPEED_FACTOR),
  TYPE_DELAY: Math.round(45 * SPEED_FACTOR),
};

/**
 * Pauses execution for presentation readability.
 */
export async function demoPause(page: Page, ms: number = PACING.STANDARD): Promise<void> {
  await page.waitForTimeout(ms);
}

/**
 * Pause between major sections to let viewers absorb the transition.
 */
export async function sectionPause(page: Page, ms: number = PACING.SECTION): Promise<void> {
  await page.waitForTimeout(ms);
}

/**
 * Ensures page is fully loaded and ready for interaction.
 */
export async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  // Brief pause for client-side JS & animations
  await page.waitForTimeout(PACING.MICRO);
}

/**
 * Smoothly moves mouse to the center of a target element.
 */
export async function smoothMove(page: Page, target: Locator): Promise<void> {
  try {
    if (await target.isVisible()) {
      const box = await target.boundingBox();
      if (box) {
        const targetX = box.x + box.width / 2;
        const targetY = box.y + box.height / 2;
        await page.mouse.move(targetX, targetY, { steps: 12 });
      }
    }
  } catch {
    // If bounding box cannot be computed, continue gracefully
  }
}

/**
 * Simulates a natural human click: move -> hover pause -> highlight -> click -> result pause.
 */
export async function slowClick(
  page: Page,
  target: Locator,
  description?: string
): Promise<void> {
  await target.scrollIntoViewIfNeeded().catch(() => {});
  await smoothMove(page, target);
  await page.waitForTimeout(Math.round(250 * SPEED_FACTOR));
  
  // Highlight target element briefly
  await highlightElement(page, target);
  
  await target.click();
  await page.waitForTimeout(Math.round(400 * SPEED_FACTOR));
}

/**
 * Simulates realistic keyboard typing.
 */
export async function typeNaturally(
  locator: Locator,
  text: string,
  delayMs: number = PACING.TYPE_DELAY
): Promise<void> {
  await locator.fill('');
  await locator.pressSequentially(text, { delay: delayMs });
}

/**
 * Smoothly scrolls the window to a given Y coordinate.
 */
export async function smoothScroll(
  page: Page,
  targetY: number,
  durationMs: number = 600
): Promise<void> {
  await page.evaluate(
    ({ y, duration }) => {
      return new Promise<void>((resolve) => {
        const startY = window.scrollY;
        const diff = y - startY;
        const startTime = performance.now();

        function step(now: number) {
          const elapsed = now - startTime;
          const progress = Math.min(elapsed / duration, 1);
          // Ease-in-out quadratic
          const ease = progress < 0.5 ? 2 * progress * progress : -1 + (4 - 2 * progress) * progress;
          window.scrollTo(0, startY + diff * ease);
          if (progress < 1) {
            requestAnimationFrame(step);
          } else {
            resolve();
          }
        }
        requestAnimationFrame(step);
      });
    },
    { y: targetY, duration: durationMs }
  );
  await page.waitForTimeout(PACING.MICRO);
}

/**
 * Injects a subtle, premium spotlight glow around an element to draw the viewer's eye.
 */
export async function highlightElement(page: Page, locator: Locator): Promise<void> {
  try {
    await locator.evaluate((el) => {
      const originalOutline = el.style.outline;
      const originalBoxShadow = el.style.boxShadow;
      const originalTransition = el.style.transition;

      el.style.transition = 'all 0.25s ease-in-out';
      el.style.outline = '2px solid rgba(37, 99, 235, 0.85)';
      el.style.boxShadow = '0 0 16px rgba(37, 99, 235, 0.45)';

      setTimeout(() => {
        el.style.outline = originalOutline;
        el.style.boxShadow = originalBoxShadow;
        el.style.transition = originalTransition;
      }, 750);
    });
  } catch {
    // Ignore if evaluate fails on detached node
  }
}

/**
 * Injects an ultra-clean, elegant HUD banner at top of viewport for presentation chapters.
 */
export async function showDemoBanner(
  page: Page,
  sectionNumber: string,
  title: string,
  subtitle: string
): Promise<void> {
  await page.evaluate(
    ({ number, t, sub }) => {
      let banner = document.getElementById('demo-hud-banner');
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'demo-hud-banner';
        banner.style.position = 'fixed';
        banner.style.top = '16px';
        banner.style.right = '24px';
        banner.style.zIndex = '999999';
        banner.style.display = 'flex';
        banner.style.alignItems = 'center';
        banner.style.gap = '14px';
        banner.style.padding = '12px 20px';
        banner.style.background = 'rgba(15, 23, 42, 0.92)';
        banner.style.backdropFilter = 'blur(12px)';
        banner.style.webkitBackdropFilter = 'blur(12px)';
        banner.style.border = '1px solid rgba(255, 255, 255, 0.15)';
        banner.style.borderRadius = '14px';
        banner.style.boxShadow = '0 10px 30px rgba(0, 0, 0, 0.35)';
        banner.style.fontFamily = "system-ui, -apple-system, 'Inter', sans-serif";
        banner.style.color = '#ffffff';
        banner.style.pointerEvents = 'none';
        banner.style.transition = 'all 0.35s cubic-bezier(0.16, 1, 0.3, 1)';
        banner.style.transform = 'translateY(-10px)';
        banner.style.opacity = '0';
        document.body.appendChild(banner);
      }

      banner.innerHTML = `
        <div style="width: 36px; height: 36px; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #7c3aed); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; color: #fff; flex-shrink: 0; box-shadow: 0 4px 10px rgba(37,99,235,0.4);">
          ${number}
        </div>
        <div>
          <div style="font-weight: 700; font-size: 14px; color: #ffffff; letter-spacing: -0.01em; line-height: 1.2;">
            ${t}
          </div>
          <div style="font-size: 11.5px; color: rgba(255, 255, 255, 0.72); margin-top: 2px; line-height: 1.2;">
            ${sub}
          </div>
        </div>
      `;

      requestAnimationFrame(() => {
        if (banner) {
          banner.style.transform = 'translateY(0)';
          banner.style.opacity = '1';
        }
      });
    },
    { number: sectionNumber, t: title, sub: subtitle }
  );

  await page.waitForTimeout(PACING.MICRO);
}

/**
 * Hides the HUD banner smoothly.
 */
export async function hideDemoBanner(page: Page): Promise<void> {
  await page.evaluate(() => {
    const banner = document.getElementById('demo-hud-banner');
    if (banner) {
      banner.style.transform = 'translateY(-10px)';
      banner.style.opacity = '0';
    }
  });
}

/**
 * Initializes error and network monitoring on the page.
 */
export function setupDemoMonitoring(page: Page): {
  getErrors: () => string[];
} {
  const severeErrors: string[] = [];

  page.on('pageerror', (err) => {
    severeErrors.push(`[PageError] ${err.message}`);
    console.error(`🔴 Uncaught Page Error: ${err.message}`);
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // Filter out non-fatal expected warnings
      if (
        !text.includes('favicon.ico') &&
        !text.includes('tailwindcss') &&
        !text.includes('404')
      ) {
        severeErrors.push(`[ConsoleError] ${text}`);
      }
    }
  });

  page.on('response', (response) => {
    if (response.status() >= 500) {
      const url = response.url();
      severeErrors.push(`[HTTP ${response.status()}] ${url}`);
      console.error(`🔴 Server Error (HTTP ${response.status()}) on ${url}`);
    }
  });

  return {
    getErrors: () => severeErrors,
  };
}
