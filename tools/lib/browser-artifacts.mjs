import fs from 'node:fs/promises';
import path from 'node:path';

export const BROWSERS = {};
const PAGE_DIALOG_EVENTS = new WeakMap();
const PAGE_DIALOG_POLICY = new WeakMap();

export function setBrowserTypes(types) {
  Object.assign(BROWSERS, types);
}

export async function ensureDirectory(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

export async function writeJson(filePath, data) {
  await fs.writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
}

export async function writeText(filePath, content) {
  await fs.writeFile(filePath, content, 'utf8');
}

export function normalizeText(value) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function installDialogHandling(page, { action = 'dismiss' } = {}) {
  if (!PAGE_DIALOG_EVENTS.has(page)) {
    PAGE_DIALOG_EVENTS.set(page, []);
    PAGE_DIALOG_POLICY.set(page, { action, promptText: '' });
    page.on('dialog', async (dialog) => {
      const events = PAGE_DIALOG_EVENTS.get(page) || [];
      const policy = PAGE_DIALOG_POLICY.get(page) || { action: 'dismiss', promptText: '' };
      events.push({
        type: dialog.type(),
        message: dialog.message(),
        handled_as: policy.action,
        prompt_text: policy.promptText || ''
      });
      PAGE_DIALOG_EVENTS.set(page, events);
      if (policy.action === 'accept') {
        if (dialog.type() === 'prompt' && policy.promptText) {
          await dialog.accept(policy.promptText);
        } else {
          await dialog.accept();
        }
      } else {
        await dialog.dismiss();
      }
    });
  } else {
    PAGE_DIALOG_POLICY.set(page, { action, promptText: '' });
  }
}

export function consumeDialogEvents(page) {
  const events = PAGE_DIALOG_EVENTS.get(page) || [];
  PAGE_DIALOG_EVENTS.set(page, []);
  return events;
}

export function setDialogHandling(page, { action = 'dismiss', promptText = '' } = {}) {
  PAGE_DIALOG_POLICY.set(page, { action, promptText });
}

export async function captureAxTree(page, browserName) {
  if (browserName !== 'chromium') {
    return {
      format: 'unsupported',
      browser: browserName,
      nodes: []
    };
  }

  const client = await page.context().newCDPSession(page);
  try {
    return await client.send('Accessibility.getFullAXTree');
  } finally {
    await client.detach();
  }
}

export async function capturePageState(page) {
  return await page.evaluate(() => {
    const INTERACTIVE_SELECTOR = [
      'a[href]',
      'button',
      'input:not([type="hidden"])',
      'select',
      'textarea',
      'summary',
      '[contenteditable="true"]',
      '[tabindex]',
      '[role="button"]',
      '[role="link"]',
      '[role="menuitem"]',
      '[role="menuitemcheckbox"]',
      '[role="menuitemradio"]',
      '[role="option"]',
      '[role="checkbox"]',
      '[role="radio"]',
      '[role="switch"]',
      '[role="tab"]',
      '[role="textbox"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[role="slider"]',
      '[role="spinbutton"]'
    ].join(',');

    function normalizeText(value) {
      return String(value ?? '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function isVisible(element) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (style.display === 'none' || style.visibility === 'hidden') {
        return false;
      }
      return rect.width > 0 && rect.height > 0;
    }

    function parseBooleanAttribute(value) {
      if (value === null || value === undefined) {
        return null;
      }
      if (value === '' || value === 'true') {
        return true;
      }
      if (value === 'false') {
        return false;
      }
      return null;
    }

    function getLabelTextById(id) {
      const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      return label ? normalizeText(label.textContent || '') : '';
    }

    function getAriaLabelledByText(value) {
      if (!value) {
        return '';
      }
      const ids = value.split(/\s+/).filter(Boolean);
      return normalizeText(
        ids
          .map((id) => document.getElementById(id))
          .filter(Boolean)
          .map((node) => node.textContent || '')
          .join(' ')
      );
    }

    function inferRole(element) {
      const explicitRole = normalizeText(element.getAttribute('role'));
      if (explicitRole) {
        return explicitRole;
      }

      const tag = element.tagName.toLowerCase();
      if (tag === 'a' && element.hasAttribute('href')) return 'link';
      if (tag === 'button') return 'button';
      if (tag === 'select') return 'combobox';
      if (tag === 'textarea') return 'textbox';
      if (tag === 'summary') return 'button';
      if (tag === 'option') return 'option';
      if (tag === 'input') {
        const type = (element.getAttribute('type') || 'text').toLowerCase();
        if (type === 'checkbox') return 'checkbox';
        if (type === 'radio') return 'radio';
        if (type === 'range') return 'slider';
        if (type === 'number') return 'spinbutton';
        if (['button', 'submit', 'reset'].includes(type)) return 'button';
        return 'textbox';
      }
      return tag;
    }

    function getAccessibleName(element) {
      const ariaLabel = normalizeText(element.getAttribute('aria-label'));
      if (ariaLabel) return ariaLabel;

      const labelledBy = getAriaLabelledByText(element.getAttribute('aria-labelledby'));
      if (labelledBy) return labelledBy;

      if (element instanceof HTMLInputElement) {
        if (element.id) {
          const byFor = getLabelTextById(element.id);
          if (byFor) return byFor;
        }
        const ariaPlaceholder = normalizeText(element.getAttribute('placeholder'));
        if (ariaPlaceholder) return ariaPlaceholder;
        const value = normalizeText(element.value);
        if (value) return value;
      }

      if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
        if (element.id) {
          const byFor = getLabelTextById(element.id);
          if (byFor) return byFor;
        }
      }

      const alt = normalizeText(element.getAttribute('alt'));
      if (alt) return alt;

      const title = normalizeText(element.getAttribute('title'));
      if (title) return title;

      const text = normalizeText(element.innerText || element.textContent || '');
      if (text) return text;

      return normalizeText(element.getAttribute('name'));
    }

    function getDescription(element) {
      const describedBy = getAriaLabelledByText(element.getAttribute('aria-describedby'));
      if (describedBy) return describedBy;

      const title = normalizeText(element.getAttribute('title'));
      if (title && title !== getAccessibleName(element)) return title;

      if (element instanceof HTMLAnchorElement) {
        return normalizeText(element.href);
      }

      return '';
    }

    function isDisabled(element) {
      if ('disabled' in element && element.disabled) {
        return true;
      }
      return element.getAttribute('aria-disabled') === 'true';
    }

    function isKeyboardReachable(element) {
      if (isDisabled(element) || !isVisible(element)) {
        return false;
      }
      const tabindex = element.getAttribute('tabindex');
      if (tabindex === '-1') {
        return false;
      }
      return true;
    }

    function getElementText(element) {
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        return normalizeText(element.value || '');
      }
      return normalizeText(element.innerText || element.textContent || '');
    }

    function nextAvailableRef(usedRefs) {
      let index = 1;
      while (usedRefs.has(`e${index}`)) {
        index += 1;
      }
      return `e${index}`;
    }

    function candidateRecord(element, ref) {
      const rect = element.getBoundingClientRect();
      const states = {
        enabled: !isDisabled(element),
        expanded: parseBooleanAttribute(element.getAttribute('aria-expanded')),
        selected: parseBooleanAttribute(element.getAttribute('aria-selected')),
        checked:
          element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type)
            ? Boolean(element.checked)
            : parseBooleanAttribute(element.getAttribute('aria-checked')),
        pressed: parseBooleanAttribute(element.getAttribute('aria-pressed')),
        focused: document.activeElement === element,
        invalid:
          element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement ||
          element instanceof HTMLSelectElement
            ? !element.checkValidity()
            : parseBooleanAttribute(element.getAttribute('aria-invalid')),
        required:
          element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement ||
          element instanceof HTMLSelectElement
            ? Boolean(element.required)
            : parseBooleanAttribute(element.getAttribute('aria-required'))
      };

      return {
        ref,
        role: inferRole(element),
        name: getAccessibleName(element),
        description: getDescription(element),
        text: getElementText(element),
        tag: element.tagName.toLowerCase(),
        value:
          element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement ||
          element instanceof HTMLSelectElement
            ? normalizeText(element.value)
            : null,
        keyboard_reachable: isKeyboardReachable(element),
        bounds: {
          x: Number(rect.x.toFixed(2)),
          y: Number(rect.y.toFixed(2)),
          width: Number(rect.width.toFixed(2)),
          height: Number(rect.height.toFixed(2))
        },
        states
      };
    }

    const seen = new Set();
    const elements = Array.from(document.querySelectorAll(`${INTERACTIVE_SELECTOR}, [data-nexui-ref]`))
      .filter((element) => {
        if (seen.has(element)) {
          return false;
        }
        seen.add(element);
        return !element.closest('[inert]') && isVisible(element);
      });

    const usedRefs = new Set(
      elements
        .map((element) => normalizeText(element.getAttribute('data-nexui-ref')))
        .filter((value) => /^e[0-9]+$/.test(value))
    );

    const assignedRefs = new Set();
    const candidates = elements.map((element) => {
      let ref = normalizeText(element.getAttribute('data-nexui-ref'));
      if (!/^e[0-9]+$/.test(ref) || assignedRefs.has(ref)) {
        ref = nextAvailableRef(usedRefs);
      }
      usedRefs.add(ref);
      assignedRefs.add(ref);
      element.setAttribute('data-nexui-ref', ref);
      return candidateRecord(element, ref);
    });

    const focusElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTarget = focusElement ? focusElement.getAttribute('data-nexui-ref') : null;

    function getModalState() {
      const dialog = document.querySelector(
        'dialog[open], [role="dialog"], [aria-modal="true"], .modal.show, .modal[style*="display: block"], .modal, .modal-dialog, .modal-content'
      );
      if (dialog && isVisible(dialog)) return 'dialog_open';
      const menu = document.querySelector('[role="menu"], [role="menubar"]');
      if (menu && isVisible(menu)) return 'menu_open';
      return 'none';
    }

    function elementLine(element) {
      const role = inferRole(element);
      const name = getAccessibleName(element);
      const text = getElementText(element);
      const label = name || text;

      if (/^H[1-6]$/.test(element.tagName)) {
        return `Heading level ${element.tagName.slice(1)}: ${label}`;
      }

      if (role === 'button') return `Button: ${label}`;
      if (role === 'link') return `Link: ${label}`;
      if (role === 'textbox') return `Textbox: ${label}`;
      if (role === 'checkbox') return `Checkbox: ${label}`;
      if (role === 'radio') return `Radio: ${label}`;
      if (role === 'combobox') return `Combobox: ${label}`;
      if (role === 'menuitem') return `Menu item: ${label}`;

      const landmarkRole = normalizeText(element.getAttribute('role'));
      if (landmarkRole) {
        return `${landmarkRole}: ${label}`.trim();
      }

      if (['main', 'nav', 'header', 'footer', 'aside'].includes(element.tagName.toLowerCase())) {
        return `${element.tagName.toLowerCase()}: ${label}`.trim();
      }

      if (element.tagName.toLowerCase() === 'p') return `Paragraph: ${label}`;
      if (element.tagName.toLowerCase() === 'li') return `List item: ${label}`;
      return label;
    }

    const readerNodes = Array.from(
      document.querySelectorAll(
        'main,nav,header,footer,aside,[role="main"],[role="navigation"],[role="banner"],[role="contentinfo"],[role="region"],h1,h2,h3,h4,h5,h6,button,a[href],input:not([type="hidden"]),select,textarea,[role="button"],[role="link"],[role="menuitem"],[role="textbox"],[role="checkbox"],[role="radio"],[role="combobox"],p,li'
      )
    ).filter((element) => isVisible(element));

    const readerLines = [];
    const emitted = new Set();
    for (const element of readerNodes) {
      if (emitted.has(element)) {
        continue;
      }
      emitted.add(element);
      const line = normalizeText(elementLine(element));
      if (line) {
        readerLines.push(line);
      }
    }

    return {
      html: document.documentElement.outerHTML,
      title: document.title,
      url: window.location.href,
      candidates,
      focusTarget,
      modalState: getModalState(),
      readerView: readerLines.join('\n')
    };
  });
}

export async function collectSnapshotArtifacts(page, options) {
  const state = await capturePageState(page);
  const axTree = await captureAxTree(page, options.browser);
  const ariaSnapshot = await page.locator('body').ariaSnapshot();
  const metadata = {
    url: state.url,
    title: state.title,
    locale: options.locale,
    viewport: {
      width: options.viewportWidth,
      height: options.viewportHeight
    },
    focus_target: state.focusTarget,
    modal_state: state.modalState,
    captured_at: new Date().toISOString(),
    browser: options.browser,
    wait_until: options.waitUntil,
    delay_ms: options.delayMs
  };

  return {
    url: state.url,
    title: state.title,
    candidate_count: state.candidates.length,
    modal_state: state.modalState,
    candidates: state.candidates,
    metadata,
    dom: {
      url: state.url,
      title: state.title,
      html: state.html
    },
    ax_tree: axTree,
    aria_snapshot: ariaSnapshot,
    reader_view: `${state.readerView}\n`
  };
}

export async function writeSnapshotBundle(page, options) {
  const snapshotDir = path.resolve(options.snapshotDir);
  await ensureDirectory(snapshotDir);

  const artifacts = await collectSnapshotArtifacts(page, options);

  await page.screenshot({
    path: path.join(snapshotDir, 'screenshot.png'),
    fullPage: true
  });
  await writeJson(path.join(snapshotDir, 'dom.json'), artifacts.dom);
  await writeJson(path.join(snapshotDir, 'ax_tree.json'), artifacts.ax_tree);
  await writeText(path.join(snapshotDir, 'aria_snapshot.yml'), artifacts.aria_snapshot);
  await writeText(path.join(snapshotDir, 'reader_view.txt'), artifacts.reader_view);
  await writeJson(path.join(snapshotDir, 'candidates.json'), artifacts.candidates);
  await writeJson(path.join(snapshotDir, 'metadata.json'), artifacts.metadata);

  return {
    snapshot_dir: snapshotDir,
    ...artifacts
  };
}

async function ensureResolvableLocator(locator, actionType) {
  const count = await locator.count();
  if (count === 0) {
    throw new Error(`Resolved element for ${actionType} was not found`);
  }
}

async function assignSyntheticRef(locator, actionType) {
  return await locator.evaluate((element, type) => {
    function isVisible(node) {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      if (style.display === 'none' || style.visibility === 'hidden') {
        return false;
      }
      return rect.width > 0 && rect.height > 0;
    }

    if (!isVisible(element)) {
      throw new Error(`Resolved element for ${type} is not visible`);
    }

    const existing = String(element.getAttribute('data-nexui-ref') || '').trim();
    if (/^e[0-9]+$/.test(existing)) {
      return { ref: existing, synthetic: false };
    }

    const used = new Set(
      Array.from(document.querySelectorAll('[data-nexui-ref]'))
        .map((node) => String(node.getAttribute('data-nexui-ref') || '').trim())
        .filter((value) => /^e[0-9]+$/.test(value))
    );
    let index = 1;
    while (used.has(`e${index}`)) {
      index += 1;
    }
    const ref = `e${index}`;
    element.setAttribute('data-nexui-ref', ref);
    return { ref, synthetic: true };
  }, actionType);
}

export async function resolveActionTarget(page, action) {
  if (!['click', 'type', 'select', 'focus'].includes(action.type)) {
    return { ref: null, locator: null, synthetic: false };
  }

  if (typeof action.target === 'string' && action.target.startsWith('e')) {
    const locator = page.locator(`[data-nexui-ref="${action.target}"]`).first();
    return { ref: action.target, locator, synthetic: false };
  }

  let locator;
  if (action.target_selector) {
    locator = page.locator(action.target_selector).first();
  } else if (action.target_role) {
    const roleOptions = {};
    if (action.target_name) {
      roleOptions.name = action.target_name;
      roleOptions.exact = true;
    }
    locator = page.getByRole(action.target_role, roleOptions).first();
  } else if (action.target_text) {
    locator = page.getByText(action.target_text, { exact: true }).first();
  } else {
    throw new Error(`Action ${action.type} requires target, target_selector, target_role, or target_text`);
  }

  await ensureResolvableLocator(locator, action.type);
  const { ref, synthetic } = await assignSyntheticRef(locator, action.type);
  return { ref, locator, synthetic };
}

export async function canonicalizeAction(page, action) {
  if (action.type === 'finish') {
    return {
      action: {
        type: 'finish',
        summary: action.summary
      }
    };
  }
  if (action.type === 'ask_user') {
    return {
      action: {
        type: 'ask_user',
        question: action.question
      }
    };
  }
  if (action.type === 'press') {
    return {
      action: {
        type: 'press',
        key: action.key
      }
    };
  }
  if (action.type === 'wait') {
    return {
      action: {
        type: 'wait'
      },
      durationMs: Number(action.duration_ms || action.delay_ms || 1000)
    };
  }
  if (action.type === 'back') {
    return {
      action: {
        type: 'back'
      }
    };
  }

  const { ref, locator, synthetic } = await resolveActionTarget(page, action);
  if (action.type === 'click') {
    return { action: { type: 'click', target: ref }, locator, syntheticTarget: synthetic };
  }
  if (action.type === 'focus') {
    return { action: { type: 'focus', target: ref }, locator, syntheticTarget: synthetic };
  }
  if (action.type === 'type') {
    return { action: { type: 'type', target: ref, text: action.text ?? '' }, locator, syntheticTarget: synthetic };
  }
  if (action.type === 'select') {
    return { action: { type: 'select', target: ref, option: action.option }, locator, syntheticTarget: synthetic };
  }
  throw new Error(`Unsupported recorder action type: ${action.type}`);
}

export async function executeCanonicalAction(page, canonical, options) {
  const timeout = options.timeoutMs;
  const action = canonical.action;
  const locator = canonical.locator;

  switch (action.type) {
    case 'click':
      await locator.click({ timeout });
      return;
    case 'focus':
      await locator.focus({ timeout });
      return;
    case 'type':
      await locator.fill(action.text, { timeout });
      return;
    case 'select':
      await locator.selectOption(action.option, { timeout });
      return;
    case 'press':
      await page.keyboard.press(action.key);
      return;
    case 'wait':
      await page.waitForTimeout(canonical.durationMs || 1000);
      return;
    case 'back':
      await page.goBack({ waitUntil: options.waitUntil, timeout });
      return;
    default:
      throw new Error(`Unsupported canonical action type: ${action.type}`);
  }
}

export async function maybeWaitAfterAction(page, step, options) {
  if (step.wait_until) {
    await page.waitForLoadState(step.wait_until, { timeout: options.timeoutMs });
  } else if (options.waitUntil !== 'commit') {
    try {
      await page.waitForLoadState(options.waitUntil, { timeout: options.timeoutMs });
    } catch (error) {
      if (!String(error?.message || '').includes('Timeout')) {
        throw error;
      }
    }
  }

  const delayMs = Number(step.post_delay_ms || 0);
  if (delayMs > 0) {
    await page.waitForTimeout(delayMs);
  }
}
