import { normalizeText } from './browser-artifacts.mjs';

const TEXT_ASSERTION_ARTIFACTS = new Set(['reader_view', 'aria_snapshot', 'dom', 'any_text']);
const MODAL_STATES = new Set(['none', 'dialog_open', 'menu_open']);

export function evaluateAssertions(artifacts, assertions, label = 'assertion') {
  const results = [];
  let passed = true;
  for (let index = 0; index < assertions.length; index += 1) {
    const assertion = assertions[index];
    const result = evaluateAssertion(artifacts, assertion);
    results.push({
      ...result,
      label,
      index: index + 1
    });
    passed = passed && result.passed;
  }
  return { passed, results };
}

export function formatAssertionResults(results) {
  return results.map((result) => {
    const status = result.passed ? 'passed' : 'failed';
    return `${result.label} ${result.index}: ${status} - ${result.message}`;
  });
}

export function evaluateAssertion(artifacts, assertion) {
  const assertionType = assertion.type;
  if (!assertionType) {
    throw new Error('Assertion must include a type.');
  }

  if (assertionType === 'url_contains') {
    const value = String(assertion.value);
    return {
      passed: String(artifacts.metadata?.url || '').includes(value),
      message: `url contains ${JSON.stringify(value)}`
    };
  }

  if (assertionType === 'modal_state_is') {
    const value = String(assertion.value);
    if (!MODAL_STATES.has(value)) {
      throw new Error(`Unsupported modal state: ${value}`);
    }
    return {
      passed: String(artifacts.metadata?.modal_state || '') === value,
      message: `modal state is ${JSON.stringify(value)}`
    };
  }

  if (assertionType === 'text_present' || assertionType === 'text_absent') {
    const value = normalizeText(assertion.value).toLowerCase();
    const haystack = normalizeText(gatherTextHaystack(artifacts, assertion.artifact || 'any_text')).toLowerCase();
    const found = haystack.includes(value);
    const expected = assertionType === 'text_present';
    return {
      passed: found === expected,
      message: `text ${expected ? 'present' : 'absent'} ${JSON.stringify(assertion.value)}`
    };
  }

  if (
    assertionType === 'candidate_exists' ||
    assertionType === 'candidate_missing' ||
    assertionType === 'field_enabled' ||
    assertionType === 'field_disabled' ||
    assertionType === 'field_value_equals'
  ) {
    const candidate = findMatchingCandidate(artifacts.candidates || [], assertion.match || {});
    if (assertionType === 'candidate_exists') {
      return {
        passed: candidate !== null,
        message: `candidate exists for ${JSON.stringify(assertion.match)}`
      };
    }
    if (assertionType === 'candidate_missing') {
      return {
        passed: candidate === null,
        message: `candidate missing for ${JSON.stringify(assertion.match)}`
      };
    }
    if (candidate === null) {
      return {
        passed: false,
        message: `no candidate matched ${assertionType} matcher ${JSON.stringify(assertion.match)}`
      };
    }
    if (assertionType === 'field_enabled' || assertionType === 'field_disabled') {
      const actualEnabled = Boolean(candidate.states?.enabled);
      const expectedEnabled = assertionType === 'field_enabled';
      return {
        passed: actualEnabled === expectedEnabled,
        message: `field is ${expectedEnabled ? 'enabled' : 'disabled'}`
      };
    }
    const actualValue = normalizeText(candidate.value);
    const expectedValue = normalizeText(assertion.value);
    return {
      passed: actualValue === expectedValue,
      message: `field value equals ${JSON.stringify(expectedValue)}`
    };
  }

  throw new Error(`Unsupported assertion type: ${assertionType}`);
}

function gatherTextHaystack(artifacts, artifact) {
  if (!TEXT_ASSERTION_ARTIFACTS.has(artifact)) {
    throw new Error(`Unsupported text assertion artifact: ${artifact}`);
  }
  if (artifact === 'reader_view') {
    return artifacts.reader_view || '';
  }
  if (artifact === 'aria_snapshot') {
    return artifacts.aria_snapshot || '';
  }
  if (artifact === 'dom') {
    return JSON.stringify(artifacts.dom || {});
  }
  return [
    artifacts.metadata?.title || '',
    artifacts.metadata?.url || '',
    artifacts.reader_view || '',
    artifacts.aria_snapshot || '',
    JSON.stringify(artifacts.dom || {})
  ].join('\n');
}

function findMatchingCandidate(candidates, matcher) {
  for (const candidate of candidates) {
    if (candidateMatches(candidate, matcher)) {
      return candidate;
    }
  }
  return null;
}

function candidateMatches(candidate, matcher) {
  for (const [key, expected] of Object.entries(matcher)) {
    const actual = candidate[key];
    if (key === 'states') {
      if (typeof expected !== 'object' || expected === null || Array.isArray(expected)) {
        return false;
      }
      const actualStates = actual && typeof actual === 'object' ? actual : {};
      for (const [stateKey, stateExpected] of Object.entries(expected)) {
        if (actualStates[stateKey] !== stateExpected) {
          return false;
        }
      }
      continue;
    }
    if (typeof expected === 'string') {
      if (normalizeText(actual).toLowerCase() !== normalizeText(expected).toLowerCase()) {
        return false;
      }
      continue;
    }
    if (actual !== expected) {
      return false;
    }
  }
  return true;
}
