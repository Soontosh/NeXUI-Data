import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import {
  canonicalizeAction,
  collectSnapshotArtifacts,
  setBrowserTypes,
  writeSnapshotBundle
} from './browser-artifacts.mjs';

setBrowserTypes({ chromium });

async function withPage(fn) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'en-US'
  });
  const page = await context.newPage();
  try {
    await fn(page);
  } finally {
    await context.close();
    await browser.close();
  }
}

const captureOptions = {
  browser: 'chromium',
  waitUntil: 'load',
  delayMs: 0,
  locale: 'en-US',
  viewportWidth: 1280,
  viewportHeight: 800
};

test('target_selector reuses an existing candidate ref', async () => {
  await withPage(async (page) => {
    await page.setContent(`
      <html>
        <body>
          <button id="open-settings">Open settings</button>
        </body>
      </html>
    `);

    await writeSnapshotBundle(page, {
      ...captureOptions,
      snapshotDir: 'tmp/test-existing-candidate'
    });

    const canonical = await canonicalizeAction(page, {
      type: 'click',
      target_selector: '#open-settings'
    });

    assert.equal(canonical.action.type, 'click');
    assert.match(canonical.action.target, /^e[0-9]+$/);
    assert.equal(canonical.syntheticTarget, false);
  });
});

test('target_selector promotes a visible non-candidate into the candidate set', async () => {
  await withPage(async (page) => {
    await page.setContent(`
      <html>
        <body>
          <div id="promo-close">Close promo</div>
        </body>
      </html>
    `);

    await writeSnapshotBundle(page, {
      ...captureOptions,
      snapshotDir: 'tmp/test-promoted-candidate'
    });

    const canonical = await canonicalizeAction(page, {
      type: 'click',
      target_selector: '#promo-close'
    });

    assert.equal(canonical.action.type, 'click');
    assert.match(canonical.action.target, /^e[0-9]+$/);
    assert.equal(canonical.syntheticTarget, true);

    const artifacts = await collectSnapshotArtifacts(page, captureOptions);
    const promoted = artifacts.candidates.find((candidate) => candidate.ref === canonical.action.target);
    assert.ok(promoted, 'expected promoted selector target to be present in candidates');
    assert.equal(promoted.tag, 'div');
    assert.equal(promoted.text, 'Close promo');
  });
});

test('target_selector rejects hidden or missing elements', async () => {
  await withPage(async (page) => {
    await page.setContent(`
      <html>
        <body>
          <div id="hidden-close" style="display:none">Hidden close</div>
        </body>
      </html>
    `);

    await assert.rejects(
      () =>
        canonicalizeAction(page, {
          type: 'click',
          target_selector: '#hidden-close'
        }),
      /Resolved element for click was not found|Resolved element for click is not visible/
    );

    await assert.rejects(
      () =>
        canonicalizeAction(page, {
          type: 'click',
          target_selector: '#does-not-exist'
        }),
      /Resolved element for click was not found/
    );
  });
});
