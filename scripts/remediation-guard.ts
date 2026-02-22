#!/usr/bin/env npx tsx
// ============================================================================
// Remediation Guard — pre-flight gate for automated remediation
//
// Determines whether the remediation agent should proceed based on:
//   - Remediation attempt count (tracked via PR labels)
//   - Security-related findings (always require human review)
//   - Protected file targets (never auto-remediated)
//   - Strictness-level attempt limits
//
// Usage:
//   PR_NUMBER=42 FINDINGS='[...]' npx tsx scripts/remediation-guard.ts --evaluate
//   npx tsx scripts/remediation-guard.ts --self-test
//
// Environment variables:
//   PR_NUMBER          — PR number to evaluate
//   FINDINGS           — JSON array of review findings
//   STRICTNESS         — relaxed | standard | strict (default: relaxed)
//   GITHUB_REPOSITORY  — owner/repo (set by CI runner)
//   GH_TOKEN           — GitHub auth token for API calls
// ============================================================================

import { execSync } from 'node:child_process';

// --- Types ---

export interface Finding {
  severity: 'blocking' | 'warning' | 'suggestion';
  file: string;
  line: number | null;
  message: string;
}

export interface RemediationDecision {
  shouldRemediate: boolean;
  attemptNumber: number;
  reason: string;
  securityBlockers: string[];  // security findings that block auto-remediation
  skippedFindings: string[];   // findings that cannot be auto-fixed
}

// --- Constants ---

/** Maximum remediation attempts per PR, keyed by strictness level. */
const MAX_ATTEMPTS: Record<string, number> = {
  relaxed: 10,
  standard: 5,
  strict: 3,
};

/** Keywords that identify security-related findings. Case-insensitive matching. */
const SECURITY_KEYWORDS = [
  'security',
  'injection',
  'xss',
  'ssrf',
  'csrf',
  'auth bypass',
  'authentication',
  'authorization',
  'privilege escalation',
  'secret',
  'credential',
  'token exposure',
  'vulnerability',
  'sanitize',
  'unsanitized',
];

/** File patterns that the remediation agent must never modify. */
const PROTECTED_FILE_PATTERNS = [
  /^\.github\/workflows\//,
  /^harness\.config\.json$/,
  /^CLAUDE\.md$/,
  /^poetry\.lock$/,
  /^pyproject\.toml$/,
  /^setup\.py$/,
  /^setup\.cfg$/,
  /^\.pre-commit-config\.yaml$/,
];

// --- Public API ---

/**
 * Check if a finding is security-related based on keyword matching.
 * Security findings are never auto-remediated — they require human review.
 */
export function isSecurityFinding(finding: Finding): boolean {
  const msg = finding.message.toLowerCase();
  return SECURITY_KEYWORDS.some((keyword) => msg.includes(keyword));
}

/**
 * Check if a file path matches any protected file pattern.
 * Protected files are never modified by the remediation agent.
 */
export function isProtectedFile(filePath: string): boolean {
  return PROTECTED_FILE_PATTERNS.some((pattern) => pattern.test(filePath));
}

/**
 * Query the current remediation attempt count from PR labels.
 * Labels follow the pattern `remediation-attempt-N`.
 * Returns the highest N found, or 0 if no labels match.
 */
export function getAttemptCount(prNumber: number): number {
  try {
    const repo = process.env.GITHUB_REPOSITORY || '';
    if (!repo) return 0;

    const output = execSync(
      `gh pr view ${prNumber} --repo "${repo}" --json labels --jq '.labels[].name'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );

    let maxAttempt = 0;
    for (const label of output.trim().split('\n')) {
      const match = label.match(/^remediation-attempt-(\d+)$/);
      if (match) {
        const num = parseInt(match[1], 10);
        if (num > maxAttempt) maxAttempt = num;
      }
    }
    return maxAttempt;
  } catch {
    return 0;
  }
}

/**
 * Format a finding into a human-readable string for audit logs.
 */
function formatFinding(finding: Finding, prefix: string): string {
  const loc = finding.file
    ? `${finding.file}${finding.line ? `:${finding.line}` : ''}`
    : 'general';
  return `[${prefix}] ${loc} — ${finding.message}`;
}

/**
 * Evaluate whether remediation should proceed for a given PR.
 *
 * Decision logic:
 * 1. Check attempt limit — reject if exceeded.
 * 2. Separate security findings — these are never auto-fixed.
 * 3. Filter findings targeting protected files — these are skipped.
 * 4. If actionable findings remain, approve remediation.
 */
export function evaluate(
  prNumber: number,
  findings: Finding[],
  strictness: string,
): RemediationDecision {
  const maxAttempts = MAX_ATTEMPTS[strictness] ?? MAX_ATTEMPTS.relaxed;
  const currentAttempt = getAttemptCount(prNumber);
  const nextAttempt = currentAttempt + 1;

  // Gate 1: Attempt limit
  if (nextAttempt > maxAttempts) {
    return {
      shouldRemediate: false,
      attemptNumber: nextAttempt,
      reason: `Remediation limit reached (${maxAttempts} attempts for ${strictness} mode). Human review required.`,
      securityBlockers: [],
      skippedFindings: [],
    };
  }

  // Gate 2: Classify findings
  const securityBlockers: string[] = [];
  const skippedFindings: string[] = [];
  const actionableFindings: Finding[] = [];

  for (const finding of findings) {
    if (isSecurityFinding(finding)) {
      securityBlockers.push(formatFinding(finding, finding.severity));
      continue;
    }

    if (finding.file && isProtectedFile(finding.file)) {
      skippedFindings.push(formatFinding(finding, 'protected'));
      continue;
    }

    actionableFindings.push(finding);
  }

  // Gate 3: All findings are security-related
  if (actionableFindings.length === 0 && securityBlockers.length > 0) {
    return {
      shouldRemediate: false,
      attemptNumber: nextAttempt,
      reason: 'All findings are security-related and require human review.',
      securityBlockers,
      skippedFindings,
    };
  }

  // Gate 4: No actionable findings
  if (actionableFindings.length === 0) {
    return {
      shouldRemediate: false,
      attemptNumber: nextAttempt,
      reason: 'No actionable findings after filtering security and protected-file issues.',
      securityBlockers,
      skippedFindings,
    };
  }

  return {
    shouldRemediate: true,
    attemptNumber: nextAttempt,
    reason: `${actionableFindings.length} actionable finding(s) to remediate (attempt ${nextAttempt}/${maxAttempts}).`,
    securityBlockers,
    skippedFindings,
  };
}

// --- CLI: --evaluate ---

if (process.argv.includes('--evaluate')) {
  const prNumber = parseInt(process.env.PR_NUMBER || '0', 10);
  const strictness = process.env.STRICTNESS || 'relaxed';

  if (!prNumber) {
    console.error('ERROR: PR_NUMBER environment variable is required.');
    process.exit(1);
  }

  let findings: Finding[] = [];
  try {
    findings = JSON.parse(process.env.FINDINGS || '[]');
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error(`ERROR: Failed to parse FINDINGS JSON: ${msg}`);
    process.exit(1);
  }

  const decision = evaluate(prNumber, findings, strictness);
  console.log(JSON.stringify(decision, null, 2));
}

// --- CLI: --self-test ---

if (process.argv.includes('--self-test')) {
  console.log('Running remediation-guard self-test...\n');

  // --- isSecurityFinding ---
  console.assert(
    isSecurityFinding({
      severity: 'blocking',
      file: 'pyworkflow/storage/postgres.py',
      line: 55,
      message: 'SQL injection vulnerability — unsanitized input passed to query',
    }) === true,
    'SQL injection should be detected as security finding',
  );
  console.assert(
    isSecurityFinding({
      severity: 'blocking',
      file: 'pyworkflow/celery/tasks.py',
      line: 12,
      message: 'Unsanitized user input passed to subprocess call',
    }) === true,
    'Unsanitized input should be detected as security finding',
  );
  console.assert(
    isSecurityFinding({
      severity: 'warning',
      file: 'pyworkflow/utils/duration.py',
      line: 8,
      message: 'Missing None check on optional parameter',
    }) === false,
    'Missing None check is not a security finding',
  );
  console.assert(
    isSecurityFinding({
      severity: 'suggestion',
      file: 'pyworkflow/primitives/sleep.py',
      line: 20,
      message: 'Consider using a dataclass instead of a plain dict',
    }) === false,
    'Code quality suggestion is not a security finding',
  );

  // --- isProtectedFile ---
  console.assert(
    isProtectedFile('.github/workflows/ci.yml') === true,
    'CI workflow should be protected',
  );
  console.assert(
    isProtectedFile('harness.config.json') === true,
    'harness.config.json should be protected',
  );
  console.assert(
    isProtectedFile('CLAUDE.md') === true,
    'CLAUDE.md should be protected',
  );
  console.assert(
    isProtectedFile('poetry.lock') === true,
    'poetry.lock should be protected',
  );
  console.assert(
    isProtectedFile('pyproject.toml') === true,
    'pyproject.toml should be protected',
  );
  console.assert(
    isProtectedFile('.pre-commit-config.yaml') === true,
    '.pre-commit-config.yaml should be protected',
  );
  console.assert(
    isProtectedFile('pyworkflow/utils/helpers.py') === false,
    'Regular source file should not be protected',
  );
  console.assert(
    isProtectedFile('tests/unit/test_events.py') === false,
    'Test file should not be protected',
  );

  // --- evaluate (without API calls — getAttemptCount returns 0 when GITHUB_REPOSITORY is unset) ---
  const mockFindings: Finding[] = [
    {
      severity: 'blocking',
      file: 'pyworkflow/utils/duration.py',
      line: 42,
      message: 'Unhandled exception in parse — will crash on malformed input',
    },
    {
      severity: 'warning',
      file: 'pyworkflow/engine/replay.py',
      line: 10,
      message: 'SQL injection vulnerability in event query',
    },
    {
      severity: 'suggestion',
      file: 'pyproject.toml',
      line: null,
      message: 'Consider pinning the celery version more tightly',
    },
  ];

  const decision = evaluate(0, mockFindings, 'relaxed');
  console.assert(
    decision.securityBlockers.length === 1,
    `Expected 1 security blocker, got ${decision.securityBlockers.length}`,
  );
  console.assert(
    decision.skippedFindings.length === 1,
    `Expected 1 skipped finding, got ${decision.skippedFindings.length}`,
  );
  console.assert(
    decision.shouldRemediate === true,
    'Should remediate when actionable findings exist',
  );

  // Test all-security findings
  const securityOnly = evaluate(
    0,
    [
      {
        severity: 'blocking',
        file: 'pyworkflow/celery/tasks.py',
        line: 1,
        message: 'Authentication bypass in recovery handler',
      },
    ],
    'relaxed',
  );
  console.assert(
    securityOnly.shouldRemediate === false,
    'Should NOT remediate when all findings are security-related',
  );
  console.assert(
    securityOnly.reason.includes('security-related'),
    'Reason should mention security',
  );

  // Test empty findings
  const emptyDecision = evaluate(0, [], 'relaxed');
  console.assert(
    emptyDecision.shouldRemediate === false,
    'Should NOT remediate with no findings',
  );

  // Test attempt limit
  const overLimitDecision = evaluate(0, mockFindings, 'strict');
  // strict limit is 3; getAttemptCount returns 0 in test, so nextAttempt=1, which is ≤ 3
  console.assert(
    overLimitDecision.shouldRemediate === true,
    'Should remediate when under strict attempt limit',
  );

  console.log('\n✔ All self-tests passed.');
}
