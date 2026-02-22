#!/usr/bin/env npx tsx
// ============================================================================
// Issue Planner Guard — pre-flight gate for automated issue planning
//
// Determines whether the planner agent should proceed based on:
//   - Presence of `agent:plan` label (required)
//   - Absence of blocking labels (agent:skip, wontfix, duplicate, invalid)
//   - No existing plan already posted via marker comment
//
// Usage:
//   ISSUE_JSON='{"number":1,...}' npx tsx scripts/issue-planner-guard.ts --evaluate
//   npx tsx scripts/issue-planner-guard.ts --self-test
//
// Environment variables:
//   ISSUE_JSON          — serialized GitHub issue object (from github.event.issue)
//   GITHUB_REPOSITORY   — owner/repo (set by CI runner)
//   GH_TOKEN            — GitHub auth token for API calls
// ============================================================================

import { execSync } from 'node:child_process';

// --- Types ---

export interface PlannerDecision {
  shouldPlan: boolean;
  issueNumber: number;
  issueTitle: string;
  reason: string;
  existingPlan: boolean;   // true if a plan comment already exists
  blockedLabels: string[]; // labels that prevent planning
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

/** The label required to trigger planning. */
const TRIGGER_LABEL = 'agent:plan';

/** Labels that block planning. */
const BLOCKING_LABELS = ['agent:skip', 'wontfix', 'duplicate', 'invalid'];

/** Marker comment prefix used to detect existing planner comments. */
const PLAN_MARKER_PREFIX = '<!-- issue-planner:';

// --- Public API ---

/**
 * Check if an existing plan has already been posted via marker comment.
 * Searches issue comments for `<!-- issue-planner: #N -->`.
 * Returns true if found, false otherwise.
 */
export function findExistingPlan(issueNumber: number): boolean {
  try {
    const repo = process.env.GITHUB_REPOSITORY || '';
    if (!repo) return false;

    const output = execSync(
      `gh issue view ${issueNumber} --repo "${repo}" --json comments --jq '.comments[].body'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );

    for (const line of output.split('\n')) {
      if (line.includes(PLAN_MARKER_PREFIX)) {
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Evaluate whether planning should proceed for a given issue.
 *
 * Decision logic:
 * 1. Skip pull requests — they're not issues.
 * 2. Check for `agent:plan` label — required to proceed.
 * 3. Check for blocking labels — reject if any are present.
 * 4. Check for existing plan via marker comment — skip if already planned.
 * 5. Approve for planning.
 */
export function evaluate(issue: IssuePayload, skipPlanCheck = false): PlannerDecision {
  const labelNames = issue.labels.map((l) => l.name);

  const base: Pick<PlannerDecision, 'issueNumber' | 'issueTitle'> = {
    issueNumber: issue.number,
    issueTitle: issue.title,
  };

  // Gate 1: Not an issue (PR)
  if (issue.pull_request) {
    return {
      ...base,
      shouldPlan: false,
      reason: 'Pull request — not an issue.',
      existingPlan: false,
      blockedLabels: [],
    };
  }

  // Gate 2: Missing trigger label
  if (!labelNames.includes(TRIGGER_LABEL)) {
    return {
      ...base,
      shouldPlan: false,
      reason: `Missing required label '${TRIGGER_LABEL}'.`,
      existingPlan: false,
      blockedLabels: [],
    };
  }

  // Gate 3: Blocking labels
  const blocked = labelNames.filter((l) => BLOCKING_LABELS.includes(l));
  if (blocked.length > 0) {
    return {
      ...base,
      shouldPlan: false,
      reason: `Blocked by label(s): ${blocked.join(', ')}.`,
      existingPlan: false,
      blockedLabels: blocked,
    };
  }

  // Gate 4: Existing plan (via marker comment)
  if (!skipPlanCheck) {
    const existingPlan = findExistingPlan(issue.number);
    if (existingPlan) {
      return {
        ...base,
        shouldPlan: false,
        reason: 'A plan has already been posted for this issue.',
        existingPlan: true,
        blockedLabels: [],
      };
    }
  }

  // Approved
  return {
    ...base,
    shouldPlan: true,
    reason: 'Issue approved for planning.',
    existingPlan: false,
    blockedLabels: [],
  };
}

// --- CLI: --evaluate ---

if (process.argv.includes('--evaluate')) {
  let issue: IssuePayload;
  try {
    issue = JSON.parse(process.env.ISSUE_JSON || '{}');
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error(`ERROR: Failed to parse ISSUE_JSON: ${msg}`);
    process.exit(1);
  }

  if (!issue.number) {
    console.error('ERROR: ISSUE_JSON must contain a valid issue number.');
    process.exit(1);
  }

  const decision = evaluate(issue);
  console.log(JSON.stringify(decision, null, 2));
}

// --- CLI: --self-test ---

if (process.argv.includes('--self-test')) {
  console.log('Running issue-planner-guard self-test...\n');

  // Missing trigger label
  const noLabel = evaluate(
    {
      number: 1,
      title: 'Add feature',
      body: 'Details...',
      user: { login: 'user' },
      labels: [{ name: 'bug' }],
    },
    true,
  );
  console.assert(noLabel.shouldPlan === false, 'Should not plan without agent:plan label');

  // Has trigger label, no blockers
  const ready = evaluate(
    {
      number: 10,
      title: 'Add DynamoDB storage backend',
      body: 'Implement DynamoDB as a storage backend for pyworkflow.',
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }, { name: 'enhancement' }],
    },
    true,
  );
  console.assert(ready.shouldPlan === true, 'Should plan with agent:plan label');
  console.assert(ready.issueNumber === 10, 'Issue number should be 10');

  // Blocked by label
  const blocked = evaluate(
    {
      number: 2,
      title: 'Fix replay race condition',
      body: null,
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }, { name: 'wontfix' }],
    },
    true,
  );
  console.assert(blocked.shouldPlan === false, 'Should not plan with blocking label');
  console.assert(
    blocked.blockedLabels.includes('wontfix'),
    'Should report wontfix as blocked label',
  );

  // PR (not an issue)
  const pr = evaluate(
    {
      number: 3,
      title: 'Add retry strategy',
      body: null,
      pull_request: { url: 'https://github.com/example/repo/pull/3' },
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }],
    },
    true,
  );
  console.assert(pr.shouldPlan === false, 'PR should be skipped');

  // Multiple blocking labels
  const multiBlocked = evaluate(
    {
      number: 4,
      title: 'Something',
      body: null,
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }, { name: 'duplicate' }, { name: 'invalid' }],
    },
    true,
  );
  console.assert(
    multiBlocked.blockedLabels.length === 2,
    `Expected 2 blocked labels, got ${multiBlocked.blockedLabels.length}`,
  );

  // Has agent:implement but not agent:plan
  const wrongLabel = evaluate(
    {
      number: 5,
      title: 'Add parallel step support',
      body: 'Details about parallel execution',
      user: { login: 'user' },
      labels: [{ name: 'agent:implement' }],
    },
    true,
  );
  console.assert(
    wrongLabel.shouldPlan === false,
    'Should not plan with agent:implement instead of agent:plan',
  );

  // agent:skip blocks even with agent:plan
  const skipped = evaluate(
    {
      number: 6,
      title: 'Refactor executor',
      body: 'Rewrite the main execution loop',
      user: { login: 'user' },
      labels: [{ name: 'agent:plan' }, { name: 'agent:skip' }],
    },
    true,
  );
  console.assert(skipped.shouldPlan === false, 'agent:skip should block planning');
  console.assert(
    skipped.blockedLabels.includes('agent:skip'),
    'Should report agent:skip as blocked label',
  );

  console.log('\n✔ All self-tests passed.');
}
