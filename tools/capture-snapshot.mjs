#!/usr/bin/env node

import process from 'node:process';
import { chromium, firefox, webkit } from 'playwright';
import {
  BROWSERS,
  ensureDirectory,
  installDialogHandling,
  setBrowserTypes,
  writeSnapshotBundle
} from './lib/browser-artifacts.mjs';

setBrowserTypes({ chromium, firefox, webkit });

function parseArgs(argv) {
  const options = {
    browser: 'chromium',
    waitUntil: 'load',
    delayMs: 0,
    timeoutMs: 30000,
    viewportWidth: 1440,
    viewportHeight: 900,
    locale: 'en-US',
    httpHeaders: {},
    headed: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    switch (token) {
      case '--url':
        options.url = next;
        index += 1;
        break;
      case '--snapshot-dir':
        options.snapshotDir = next;
        index += 1;
        break;
      case '--browser':
        options.browser = next;
        index += 1;
        break;
      case '--wait-until':
        options.waitUntil = next;
        index += 1;
        break;
      case '--delay-ms':
        options.delayMs = Number(next);
        index += 1;
        break;
      case '--timeout-ms':
        options.timeoutMs = Number(next);
        index += 1;
        break;
      case '--viewport-width':
        options.viewportWidth = Number(next);
        index += 1;
        break;
      case '--viewport-height':
        options.viewportHeight = Number(next);
        index += 1;
        break;
      case '--locale':
        options.locale = next;
        index += 1;
        break;
      case '--http-header': {
        const delimiterIndex = next.indexOf('=');
        if (delimiterIndex <= 0) {
          throw new Error(`Invalid --http-header value: ${next}`);
        }
        const name = next.slice(0, delimiterIndex).trim();
        const value = next.slice(delimiterIndex + 1).trim();
        if (!name) {
          throw new Error(`Invalid --http-header name: ${next}`);
        }
        options.httpHeaders[name] = value;
        index += 1;
        break;
      }
      case '--headed':
        options.headed = true;
        break;
      default:
        throw new Error(`Unknown argument: ${token}`);
    }
  }

  if (!options.url) {
    throw new Error('--url is required');
  }
  if (!options.snapshotDir) {
    throw new Error('--snapshot-dir is required');
  }
  if (!BROWSERS[options.browser]) {
    throw new Error(`Unsupported browser: ${options.browser}`);
  }

  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const snapshotDir = options.snapshotDir;
  await ensureDirectory(snapshotDir);

  const browserType = BROWSERS[options.browser];
  const browser = await browserType.launch({ headless: !options.headed });
  let context;

  try {
    context = await browser.newContext({
      locale: options.locale,
      viewport: {
        width: options.viewportWidth,
        height: options.viewportHeight
      },
      extraHTTPHeaders: options.httpHeaders
    });
    const page = await context.newPage();
    installDialogHandling(page);
    await page.goto(options.url, {
      waitUntil: options.waitUntil,
      timeout: options.timeoutMs
    });
    if (options.delayMs > 0) {
      await page.waitForTimeout(options.delayMs);
    }

    const summary = await writeSnapshotBundle(page, {
      snapshotDir,
      browser: options.browser,
      waitUntil: options.waitUntil,
      delayMs: options.delayMs,
      locale: options.locale,
      viewportWidth: options.viewportWidth,
      viewportHeight: options.viewportHeight
    });

    process.stdout.write(
      `${JSON.stringify(
        summary,
        null,
        2
      )}\n`
    );
  } finally {
    if (context) {
      await context.close();
    }
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
