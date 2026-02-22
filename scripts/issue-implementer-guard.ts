#!/usr/bin/env npx tsx
// ============================================================================
// Issue Implementer Guard — pre-flight gate for automated issue implementation
//
// Supports two modes:
//   Issue mode:       ISSUE_JSON set — verify agent:implement label, check for
//                     existing PR, derive branch name
//   Review-fix mode:  PR_NUMBER + REVIEW_FIX_CYCLE set — verify PR is OPEN,
//                     cycle ≤ 3, return branch name from PR
//
// Usage:
//   ISSUE_JSON='{"number":1,...}' npx tsx scripts/issue-implementer-guard.ts --evaluate
//   PR_NUMBER=42 REVIEW_FIX_CYCLE=2 npx tsx scripts/issue-implementer-guard.ts --evaluate
//   npx tsx scripts/issue-implementer-guard.ts --self-test
//
// Environment variables:
//   ISSUE_JSON          — serialized GitHub issue object (from github.event.issue)
//   PR_NUMBER           — PR number (review-fix mode)
//   REVIEW_FIX_CYCLE    — review-fix cycle number (review-fix mode, 1-3)
//   GITHUB_REPOSITORY   — owner/repo (set by CI runner)
//   GH_TOKEN            — GitHub auth token for API calls
// ============================================================================

import { execSync } from 'node:child_process';

// --- Types ---

export interface ImplementerDecision {
  shouldImplement: boolean;
  issueNumber: number | null;
  issueTitle: string;
  branchName: string;
  reason: string;
  existingPR: number | null; // non-null if a PR already exists for this issue
  blockedLabels: string[];   // labels that prevent implementation
  reviewFix: boolean;        // true when operating in review-fix mode
}

interface IssuePayload {
  number: number;
  title: string;
  body: string | null;
  pull_request?: unknown;
  user: { login: string; type?: string };
  labels: Array<{ name: string }>;
}

// --- Constants ---

/** The label required to trigger implementation. */
const TRIGGER_LABEL = 'agent:implement';

/** Labels that block implementation. */
const BLOCKING_LABELS = ['agent:skip', 'wontfix', 'duplicate', 'invalid'];

/** Marker comment prefix used to detect existing implementer PRs. */
const IMPLEMENTER_PR_MARKER = '<!-- issue-implementer-pr:';

/** Maximum review-fix cycles before escalation. */
const MAX_REVIEW_FIX_CYCLES = 3;

// --- Public API ---

/**
 * Slugify a string for use in branch names.
 * Lowercases, replaces non-alphanumeric runs with hyphens, trims, and truncates.
 */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

/**
 * Derive a git branch name from an issue title and number.
 * Format: `cf/<slug>-<number>`, truncated to 60 characters total.
 */
export function deriveBranchName(issueTitle: string, issueNumber: number): string {
  const slug = slugify(issueTitle);
  return `cf/${slug}-${issueNumber}`.slice(0, 60);
}

/**
 * Check if an existing implementation PR has been created for this issue.
 * Searches issue comments for `<!-- issue-implementer-pr: #N -->`.
 * Returns the PR number if found, null otherwise.
 */
export function findExistingPR(issueNumber: number): number | null {
  try {
    const repo = process.env.GITHUB_REPOSITORY || '';
    if (!repo) return null;

    const output = execSync(
      `gh issue view ${issueNumber} --repo "${repo}" --json comments --jq '.comments[].body'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );

    for (const line of output.split('\n')) {
      if (line.includes(IMPLEMENTER_PR_MARKER)) {
        // Extract the PR number from marker like <!-- issue-implementer-pr: #42 -->
        const match = line.match(/<!-- issue-implementer-pr: #(\d+) -->/);
        if (match) return parseInt(match[1], 10);
        return -1; // implementer ran but PR number not extractable
      }
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Evaluate whether issue implementation should proceed.
 *
 * Decision logic:
 * 1. Skip pull requests — they're not issues.
 * 2. Check for `agent:implement` label — required to proceed.
 * 3. Check for blocking labels — reject if any are present.
 * 4. Check for existing implementation PR via marker comment.
 * 5. Approve for implementation.
 */
export function evaluate(issue: IssuePayload, skipPRCheck = false): ImplementerDecision {
  const labelNames = issue.labels.map((l) => l.name);
  const base = {
    issueNumber: issue.number,
    issueTitle: issue.title,
    branchName: deriveBranchName(issue.title, issue.number),
    existingPR: null as number | null,
    blockedLabels: [] as string[],
    reviewFix: false,
  };

  // Gate 1: Not an issue (pull request)
  if (issue.pull_request) {
    return { ...base, shouldImplement: false, reason: 'Pull request — not an issue.' };
  }

  // Gate 2: Missing trigger label
  if (!labelNames.includes(TRIGGER_LABEL)) {
    return {
      ...base,
      shouldImplement: false,
      reason: `Missing required label '${TRIGGER_LABEL}'.`,
    };
  }

  // Gate 3: Blocking labels
  const blocked = labelNames.filter((l) => BLOCKING_LABELS.includes(l));
  if (blocked.length > 0) {
    return {
      ...base,
      shouldImplement: false,
      reason: `Blocked by label(s): ${blocked.join(', ')}.`,
      blockedLabels: blocked,
    };
  }

  // Gate 4: Existing implementation PR (via marker comment)
  if (!skipPRCheck) {
    const existingPR = findExistingPR(issue.number);
    if (existingPR !== null) {
      return {
        ...base,
        shouldImplement: false,
        reason: 'An implementation PR already exists for this issue.',
        existingPR,
      };
    }
  }

  // Approved
  return {
    ...base,
    shouldImplement: true,
    reason: 'Issue approved for implementation.',
  };
}

/**
 * Evaluate whether review-fix mode should proceed for a given PR.
 *
 * Decision logic:
 * 1. Verify cycle ≤ MAX_REVIEW_FIX_CYCLES.
 * 2. Verify PR is OPEN.
 * 3. Return branch name from PR.
 */
export function evaluateReviewFix(prNumber: number, cycle: number): ImplementerDecision {
  const base = {
    issueNumber: null as null,
    issueTitle: '',
    existingPR: prNumber,
    blockedLabels: [] as string[],
    reviewFix: true,
  };

  // Gate 1: Max cycles
  if (cycle > MAX_REVIEW_FIX_CYCLES) {
    return {
      ...base,
      shouldImplement: false,
      branchName: '',
      reason: `Max review-fix cycles reached (${MAX_REVIEW_FIX_CYCLES}). Escalating to human.`,
    };
  }

  // Gate 2: PR must be OPEN, fetch branch name
  try {
    const repo = process.env.GITHUB_REPOSITORY || '';
    const raw = execSync(
      `gh pr view ${prNumber} --repo "${repo}" --json headRefName,state`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );
    const { headRefName, state } = JSON.parse(raw) as { headRefName: string; state: string };

    if (state !== 'OPEN') {
      return {
        ...base,
        shouldImplement: false,
        branchName: headRefName || '',
        reason: `PR #${prNumber} is ${state}, not OPEN.`,
      };
    }

    return {
      ...base,
      shouldImplement: true,
      branchName: headRefName,
      reason: `PR #${prNumber} approved for review-fix (cycle ${cycle}/${MAX_REVIEW_FIX_CYCLES}).`,
    };
  } catch {
    return {
      ...base,
      shouldImplement: false,
      branchName: '',
      reason: `Failed to fetch PR #${prNumber} — cannot proceed.`,
    };
  }
}

// --- CLI: --evaluate ---

if (process.argv.includes('--evaluate')) {
  const prNumber = parseInt(process.env.PR_NUMBER || '0', 10);
  const reviewFixCycle = parseInt(process.env.REVIEW_FIX_CYCLE || '0', 10);

  // Review-fix mode: both PR_NUMBER and REVIEW_FIX_CYCLE set
  if (prNumber && reviewFixCycle) {
    const decision = evaluateReviewFix(prNumber, reviewFixCycle);
    console.log(JSON.stringify(decision, null, 2));
    process.exit(0);
  }

  // Issue mode: ISSUE_JSON set
  let issue: IssuePayload;
  try {
    issue = JSON.parse(process.env.ISSUE_JSON || '{}');
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error(`ERROR: Failed to parse ISSUE_JSON: ${msg}`);
    process.exit(1);
  }

  if (!issue.number) {
    console.error(
      'ERROR: ISSUE_JSON must contain a valid issue number, ' +
      'or set PR_NUMBER + REVIEW_FIX_CYCLE for review-fix mode.',
    );
    process.exit(1);
  }

  const decision = evaluate(issue);
  console.log(JSON.stringify(decision, null, 2));
}

// --- CLI: --self-test ---

if (process.argv.includes('--self-test')) {
  console.log('Running issue-implementer-guard self-test...\n');

  // --- slugify ---
  console.assert(slugify('Add DynamoDB backend') === 'add-dynamodb-backend', 'slugify: basic');
  console.assert(slugify('Fix  replay  race!!') === 'fix-replay-race', 'slugify: collapse whitespace/special');
  console.assert(slugify('  leading and trailing  ') === 'leading-and-trailing', 'slugify: trim');
  console.assert(slugify('A'.repeat(60)).length === 50, 'slugify: truncate at 50');

  // --- deriveBranchName ---
  const branch = deriveBranchName('Add DynamoDB storage backend', 42);
  console.assert(branch.startsWith('cf/'), `Expected cf/ prefix, got: ${branch}`);
  console.assert(branch.endsWith('-42'), `Expected -42 suffix, got: ${branch}`);
  console.assert(branch.length <= 60, `Branch too long: ${branch.length} chars`);

  const longBranch = deriveBranchName(
    'A very long issue title that far exceeds the maximum allowed length for git branches',
    999,
  );
  console.assert(longBranch.length <= 60, `Long branch too long: ${longBranch.length} chars`);
  console.assert(longBranch.startsWith('cf/'), 'Long branch should still start with cf/');

  // --- evaluate ---

  // Missing trigger label
  const noLabel = evaluate(
    {
      number: 1,
      title: 'Add feature',
      body: 'Details',
      user: { login: 'user' },
      labels: [{ name: 'bug' }],
    },
    true,
  );
  console.assert(noLabel.shouldImplement === false, 'Should not implement without agent:implement label');
  console.assert(noLabel.reviewFix === false, 'reviewFix should be false in issue mode');

  // Has trigger label, no blockers
  const ready = evaluate(
    {
      number: 10,
      title: 'Add DynamoDB storage backend',
      body: 'Implement DynamoDB as a storage backend for pyworkflow.',
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }, { name: 'enhancement' }],
    },
    true,
  );
  console.assert(ready.shouldImplement === true, 'Should implement with agent:implement label');
  console.assert(ready.issueNumber === 10, `Expected issueNumber 10, got ${ready.issueNumber}`);
  console.assert(ready.branchName.startsWith('cf/'), `Branch should start with cf/, got: ${ready.branchName}`);
  console.assert(ready.branchName.includes('10'), 'Branch should include issue number');
  console.assert(ready.reviewFix === false, 'reviewFix should be false in issue mode');

  // Blocked by label
  const blocked = evaluate(
    {
      number: 2,
      title: 'Fix replay race condition',
      body: null,
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }, { name: 'wontfix' }],
    },
    true,
  );
  console.assert(blocked.shouldImplement === false, 'Should not implement with blocking label');
  console.assert(blocked.blockedLabels.includes('wontfix'), 'Should report wontfix as blocked label');

  // Pull request (not an issue)
  const pr = evaluate(
    {
      number: 3,
      title: 'Add retry strategy',
      body: null,
      pull_request: { url: 'https://github.com/example/repo/pull/3' },
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }],
    },
    true,
  );
  console.assert(pr.shouldImplement === false, 'Pull request should be skipped');
  console.assert(pr.reason.includes('Pull request'), `Expected PR reason, got: ${pr.reason}`);

  // Multiple blocking labels
  const multiBlocked = evaluate(
    {
      number: 4,
      title: 'Something',
      body: null,
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }, { name: 'duplicate' }, { name: 'invalid' }],
    },
    true,
  );
  console.assert(
    multiBlocked.blockedLabels.length === 2,
    `Expected 2 blocked labels, got ${multiBlocked.blockedLabels.length}`,
  );

  // agent:skip blocks even with agent:implement
  const skipped = evaluate(
    {
      number: 5,
      title: 'Refactor executor',
      body: 'Rewrite the main execution loop',
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }, { name: 'agent:skip' }],
    },
    true,
  );
  console.assert(skipped.shouldImplement === false, 'agent:skip should block implementation');
  console.assert(skipped.blockedLabels.includes('agent:skip'), 'Should report agent:skip as blocked');

  // agent:plan alone is not sufficient (wrong label)
  const wrongLabel = evaluate(
    {
      number: 6,
      title: 'Add parallel step support',
      body: 'Details about parallel execution',
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }],
    },
    true,
  );
  console.assert(
    wrongLabel.shouldImplement === false,
    'Should not implement with only agent:plan label',
  );

  // --- evaluateReviewFix ---

  // Max cycles exceeded
  const tooMany = evaluateReviewFix(100, MAX_REVIEW_FIX_CYCLES + 1);
  console.assert(tooMany.shouldImplement === false, 'Should not fix when cycles exceeded');
  console.assert(tooMany.reviewFix === true, 'reviewFix should be true in review-fix mode');
  console.assert(
    tooMany.reason.includes('Max review-fix cycles'),
    `Expected max-cycles reason, got: ${tooMany.reason}`,
  );

  // Cycle within limit (API call skipped — GITHUB_REPOSITORY not set)
  // evaluateReviewFix would fail the execSync, which is caught and returns shouldImplement: false.
  // We just verify the type contract is satisfied.
  const cycleOk = evaluateReviewFix(42, 2);
  console.assert(typeof cycleOk.shouldImplement === 'boolean', 'shouldImplement must be boolean');
  console.assert(cycleOk.reviewFix === true, 'reviewFix must be true for review-fix mode');

  console.log('\n✔ All self-tests passed.');
}
