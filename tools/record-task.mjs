#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { chromium, firefox, webkit } from 'playwright';
import {
  BROWSERS,
  canonicalizeAction,
  collectSnapshotArtifacts,
  consumeDialogEvents,
  ensureDirectory,
  executeCanonicalAction,
  installDialogHandling,
  maybeWaitAfterAction,
  setDialogHandling,
  setBrowserTypes,
  writeJson,
  writeSnapshotBundle,
  writeText
} from './lib/browser-artifacts.mjs';
import { evaluateAssertions, formatAssertionResults } from './lib/success-assertions.mjs';

setBrowserTypes({ chromium, firefox, webkit });

function parseArgs(argv) {
  const options = {
    outputDir: 'examples/tasks',
    browser: 'chromium',
    waitUntil: 'load',
    delayMs: 0,
    timeoutMs: 30000,
    viewportWidth: 1440,
    viewportHeight: 900,
    locale: 'en-US',
    headed: false,
    overwrite: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    switch (token) {
      case '--recipe':
        options.recipe = next;
        index += 1;
        break;
      case '--output-dir':
        options.outputDir = next;
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
      case '--headed':
        options.headed = true;
        break;
      case '--overwrite':
        options.overwrite = true;
        break;
      default:
        throw new Error(`Unknown argument: ${token}`);
    }
  }

  if (!options.recipe) {
    throw new Error('--recipe is required');
  }
  if (!BROWSERS[options.browser]) {
    throw new Error(`Unsupported browser: ${options.browser}`);
  }
  return options;
}

async function readRecipe(recipePath) {
  const absolutePath = path.resolve(recipePath);
  const raw = await fs.readFile(absolutePath, 'utf8');
  const recipe = JSON.parse(raw);
  const recipeDir = path.dirname(absolutePath);

  if (!recipe.url && recipe.path) {
    recipe.url = pathToFileURL(path.resolve(recipeDir, recipe.path)).href;
  }
  if (!recipe.url) {
    throw new Error('Recipe must provide either `url` or `path`.');
  }
  if (!recipe.task_id) {
    throw new Error('Recipe must provide `task_id`.');
  }
  if (!Array.isArray(recipe.steps) || recipe.steps.length === 0) {
    throw new Error('Recipe must provide at least one step.');
  }
  return { recipe, absolutePath };
}

function resolveDialogPolicy(policy = {}) {
  return {
    action: policy.action === 'accept' ? 'accept' : 'dismiss',
    promptText: String(policy.prompt_text || '')
  };
}

function normalizeHttpHeaders(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => String(key || '').trim().length > 0)
      .map(([key, headerValue]) => [String(key).trim(), String(headerValue ?? '')])
  );
}

function snapshotId(index) {
  return `s${String(index).padStart(3, '0')}`;
}

function defaultSource(recipe, finalUrl, locale) {
  return {
    site_id: recipe.task_id,
    site_name: recipe.title || recipe.task_id,
    url: finalUrl,
    category: 'other',
    redistribution_class: 'redistributable_source',
    locale
  };
}

function buildTaskManifest(recipe, runtime, finalUrl) {
  const allowedActions = recipe.allowed_actions || Array.from(new Set(
    recipe.steps
      .map((step) => step.action.type)
      .filter((type) => type !== 'finish')
      .concat(['finish'])
  ));

  return {
    schema_version: '0.0',
    benchmark: 'nexui-core',
    task_id: recipe.task_id,
    title: recipe.title || recipe.task_id,
    goal: recipe.goal || recipe.instruction || `Complete task ${recipe.task_id}.`,
    instruction_file: 'instruction.md',
    user_profile_file: 'user_profile.json',
    start_snapshot: 's000',
    snapshots: runtime.snapshots,
    transitions_file: 'transitions.yaml',
    oracle_file: 'oracle/trajectory.jsonl',
    eval: {
      success_checker: 'eval/check_success.py',
      safety_rules: 'eval/safety_rules.yaml',
      explanation_rubric: 'eval/explanation_rubric.yaml'
    },
    allowed_actions: allowedActions,
    risk_level: recipe.risk_level || 'safe',
    source: {
      ...(defaultSource(recipe, finalUrl, runtime.locale)),
      ...(recipe.source || {}),
      url: (recipe.source && recipe.source.url) || finalUrl,
      locale: (recipe.source && recipe.source.locale) || runtime.locale,
      captured_at: new Date().toISOString()
    },
    difficulty_band: recipe.difficulty_band || 'medium',
    difficulty_dimensions: recipe.difficulty_dimensions || {
      authentication_required: false,
      meaningful_action_count: runtime.oracleSteps.filter((step) => {
        const type = step.action?.type;
        return type && !['finish', 'ask_user', 'wait'].includes(type);
      }).length,
      cross_view_verification: false,
      summary_edit_propagation: false,
      conditional_ui: false,
      async_or_modal: false,
      dense_controls: false,
      safety_boundary: recipe.risk_level === 'confirmation_required'
    },
    source_surface: recipe.source_surface || recipe.source?.site_id || recipe.task_id,
    split: recipe.split || 'unassigned',
    stability_runs_passed: Number(recipe.stability_runs_passed || 0),
    requires_source_reset: Boolean(recipe.requires_source_reset || false),
    success_assertions: recipe.success_assertions || [],
    success_any_of: recipe.success_any_of || [],
    tags: recipe.tags || ['recorded'],
    review_notes: recipe.review_notes || 'Generated from a recorder recipe.'
  };
}

function buildUserProfile(recipe) {
  return recipe.user_profile || {
    user_id: 'default-assistive-user',
    assistive_needs: [
      'screen-reader-compatible explanations',
      'brief state-oriented updates'
    ],
    notes: 'Replace this generated profile if the task requires a more specific user context.'
  };
}

function buildSafetyRules(recipe) {
  return recipe.safety_rules || {
    forbidden_actions: [],
    confirmation_required_actions: [],
    flag_click_xy: true
  };
}

function buildExplanationRubric(recipe) {
  return recipe.explanation_rubric || {
    step_explanation: {
      preferred_max_words: 30,
      must_describe_state_change: true
    },
    final_summary: {
      preferred_max_words: 40
    }
  };
}

function buildSuccessChecker(finalSnapshot) {
  return `from nexui.success import evaluate_success_from_manifest


def check_success(task, trace):
    return evaluate_success_from_manifest(
        task,
        trace,
        fallback_final_snapshot="${finalSnapshot}",
    )
`;
}

async function writeTaskPackage(taskDir, recipe, runtime) {
  await ensureDirectory(taskDir);
  await ensureDirectory(path.join(taskDir, 'oracle'));
  await ensureDirectory(path.join(taskDir, 'eval'));
  await ensureDirectory(path.join(taskDir, 'recording'));

  const manifest = buildTaskManifest(recipe, runtime, runtime.finalUrl);
  await writeJson(path.join(taskDir, 'task.yaml'), manifest);
  await writeText(
    path.join(taskDir, 'instruction.md'),
    `${recipe.instruction || manifest.goal}\n`
  );
  await writeJson(path.join(taskDir, 'user_profile.json'), buildUserProfile(recipe));
  await writeJson(path.join(taskDir, 'transitions.yaml'), runtime.transitions);
  await writeText(
    path.join(taskDir, 'oracle', 'trajectory.jsonl'),
    `${runtime.oracleSteps.map((step) => JSON.stringify(step)).join('\n')}\n`
  );
  await writeText(
    path.join(taskDir, 'eval', 'check_success.py'),
    buildSuccessChecker(runtime.finalSnapshot)
  );
  await writeJson(path.join(taskDir, 'eval', 'safety_rules.yaml'), buildSafetyRules(recipe));
  await writeJson(
    path.join(taskDir, 'eval', 'explanation_rubric.yaml'),
    buildExplanationRubric(recipe)
  );
  await writeJson(path.join(taskDir, 'recording', 'recipe.json'), recipe);
  await writeJson(path.join(taskDir, 'recording', 'session.json'), {
    recorded_at: new Date().toISOString(),
    final_snapshot: runtime.finalSnapshot,
    final_url: runtime.finalUrl,
    snapshot_count: runtime.snapshots.length,
    transition_count: runtime.transitions.length,
    oracle_step_count: runtime.oracleSteps.length,
    step_results: runtime.stepResults
  });
}

async function waitForStepPostconditions(page, step, captureOptions, defaultTimeoutMs) {
  const postconditions = Array.isArray(step.postconditions) ? step.postconditions : [];
  if (postconditions.length === 0) {
    return { passed: true, results: [], attempts: 0, timedOut: false };
  }

  const timeoutMs = Number(step.postcondition_timeout_ms ?? defaultTimeoutMs ?? 0);
  const pollIntervalMs = Number(step.postcondition_poll_interval_ms ?? 250);
  const start = Date.now();
  let attempts = 0;
  let latestEvaluation = null;

  while (true) {
    attempts += 1;
    const artifacts = await collectSnapshotArtifacts(page, captureOptions);
    latestEvaluation = evaluateAssertions(artifacts, postconditions, 'postcondition');
    if (latestEvaluation.passed) {
      return { ...latestEvaluation, attempts, timedOut: false };
    }

    if (timeoutMs <= 0 || Date.now() - start >= timeoutMs) {
      return { ...latestEvaluation, attempts, timedOut: true };
    }

    await page.waitForTimeout(pollIntervalMs);
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { recipe } = await readRecipe(options.recipe);
  const outputRoot = path.resolve(options.outputDir);
  const taskDir = path.join(outputRoot, recipe.task_id);

  if (options.overwrite) {
    await fs.rm(taskDir, { recursive: true, force: true });
  } else {
    try {
      await fs.access(taskDir);
      throw new Error(`Task directory already exists: ${taskDir}`);
    } catch (error) {
      if (error.code !== 'ENOENT') {
        throw error;
      }
    }
  }

  const browserType = BROWSERS[options.browser];
  const browser = await browserType.launch({ headless: !options.headed });
  let context;

  try {
    context = await browser.newContext({
      locale: recipe.locale || options.locale,
      viewport: {
        width: recipe.viewport_width || options.viewportWidth,
        height: recipe.viewport_height || options.viewportHeight
      },
      extraHTTPHeaders: normalizeHttpHeaders(recipe.http_headers)
    });
    const page = await context.newPage();
    installDialogHandling(page, resolveDialogPolicy(recipe.dialog));
    await page.goto(recipe.url, {
      waitUntil: recipe.wait_until || options.waitUntil,
      timeout: recipe.timeout_ms || options.timeoutMs
    });

    const startupDelay = Number(recipe.delay_ms ?? options.delayMs);
    if (startupDelay > 0) {
      await page.waitForTimeout(startupDelay);
    }

    const runtime = {
      locale: recipe.locale || options.locale,
      snapshots: [],
      transitions: [],
      oracleSteps: [],
      stepResults: [],
      finalSnapshot: 's000',
      finalUrl: recipe.url
    };

    let snapshotIndex = 0;
    let currentSnapshot = snapshotId(snapshotIndex);
    runtime.snapshots.push(currentSnapshot);
    await writeSnapshotBundle(page, {
      snapshotDir: path.join(taskDir, 'snapshots', currentSnapshot),
      browser: options.browser,
      waitUntil: recipe.wait_until || options.waitUntil,
      delayMs: startupDelay,
      locale: runtime.locale,
      viewportWidth: recipe.viewport_width || options.viewportWidth,
      viewportHeight: recipe.viewport_height || options.viewportHeight
    });
    consumeDialogEvents(page);

    for (const step of recipe.steps) {
      setDialogHandling(page, resolveDialogPolicy(step.dialog || recipe.dialog));
      const canonical = await canonicalizeAction(page, step.action);
      if (canonical.syntheticTarget) {
        await writeSnapshotBundle(page, {
          snapshotDir: path.join(taskDir, 'snapshots', currentSnapshot),
          browser: options.browser,
          waitUntil: recipe.wait_until || options.waitUntil,
          delayMs: startupDelay,
          locale: runtime.locale,
          viewportWidth: recipe.viewport_width || options.viewportWidth,
          viewportHeight: recipe.viewport_height || options.viewportHeight
        });
      }
      const oracleStep = {
        action: canonical.action,
        explanation: step.explanation || ''
      };
      runtime.oracleSteps.push(oracleStep);

      if (canonical.action.type === 'finish' || canonical.action.type === 'ask_user') {
        runtime.finalSnapshot = currentSnapshot;
        runtime.finalUrl = page.url();
        break;
      }

      await executeCanonicalAction(page, canonical, {
        timeoutMs: recipe.timeout_ms || options.timeoutMs,
        waitUntil: recipe.wait_until || options.waitUntil
      });
      await maybeWaitAfterAction(page, step, {
        timeoutMs: recipe.timeout_ms || options.timeoutMs,
        waitUntil: recipe.wait_until || options.waitUntil
      });
      const dialogEvents = consumeDialogEvents(page);

      const postconditionCheck = await waitForStepPostconditions(
        page,
        step,
        {
          browser: options.browser,
          waitUntil: step.wait_until || recipe.wait_until || options.waitUntil,
          delayMs: Number(step.post_delay_ms || 0),
          locale: runtime.locale,
          viewportWidth: recipe.viewport_width || options.viewportWidth,
          viewportHeight: recipe.viewport_height || options.viewportHeight
        },
        recipe.timeout_ms || options.timeoutMs
      );

      snapshotIndex += 1;
      const nextSnapshot = snapshotId(snapshotIndex);
      runtime.snapshots.push(nextSnapshot);
      const snapshotSummary = await writeSnapshotBundle(page, {
        snapshotDir: path.join(taskDir, 'snapshots', nextSnapshot),
        browser: options.browser,
        waitUntil: step.wait_until || recipe.wait_until || options.waitUntil,
        delayMs: Number(step.post_delay_ms || 0),
        locale: runtime.locale,
        viewportWidth: recipe.viewport_width || options.viewportWidth,
        viewportHeight: recipe.viewport_height || options.viewportHeight
      });

      const transitionNotes = [...(step.notes || [])];
      if (dialogEvents.length > 0) {
        transitionNotes.push(
          ...dialogEvents.map((event) => `dialog: ${event.type} - ${event.message}`)
        );
      }
      if (postconditionCheck.results.length > 0) {
        transitionNotes.push(...formatAssertionResults(postconditionCheck.results));
      }
      runtime.stepResults.push({
        step_index: runtime.stepResults.length,
        action: canonical.action,
        before_snapshot: currentSnapshot,
        after_snapshot: nextSnapshot,
        postconditions: postconditionCheck.results,
        postcondition_attempts: postconditionCheck.attempts,
        postconditions_passed: postconditionCheck.passed,
        postconditions_timed_out: postconditionCheck.timedOut,
        dialog_events: dialogEvents,
        modal_state: snapshotSummary.metadata.modal_state,
        url: snapshotSummary.metadata.url
      });

      if (!postconditionCheck.passed) {
        const detail = formatAssertionResults(postconditionCheck.results).join('; ');
        throw new Error(`Postconditions failed after step ${runtime.stepResults.length}: ${detail}`);
      }

      runtime.transitions.push({
        from: currentSnapshot,
        action: canonical.action,
        to: nextSnapshot,
        notes: transitionNotes
      });
      currentSnapshot = nextSnapshot;
      runtime.finalSnapshot = currentSnapshot;
      runtime.finalUrl = page.url();
    }

    await writeTaskPackage(taskDir, recipe, runtime);

    process.stdout.write(
      `${JSON.stringify(
        {
          task_dir: taskDir,
          task_id: recipe.task_id,
          snapshot_count: runtime.snapshots.length,
          transition_count: runtime.transitions.length,
          oracle_step_count: runtime.oracleSteps.length,
          final_snapshot: runtime.finalSnapshot,
          final_url: runtime.finalUrl
        },
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
