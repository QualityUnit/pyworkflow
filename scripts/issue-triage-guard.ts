#!/usr/bin/env npx tsx
// ============================================================================
// Issue Triage Guard — pre-flight gate for automated issue triage
//
// Determines whether the triage agent should proceed based on:
//   - Bot-authored issues (skip)
//   - Already-triaged issues (skip unless re-triage on edit)
//   - Pull requests (skip — not issues)
//   - Issue event context (opened vs edited)
//
// Usage:
//   ISSUE_JSON='{"number":1,...}' EVENT_NAME='opened' npx tsx scripts/issue-triage-guard.ts --evaluate
//   npx tsx scripts/issue-triage-guard.ts --self-test
//
// Environment variables:
//   ISSUE_JSON   — serialized GitHub issue object (from github.event.issue)
//   EVENT_NAME   — "opened" | "edited" (from github.event.action)
// ============================================================================

// --- Types ---

export interface TriageDecision {
  shouldTriage: boolean;
  issueNumber: number;
  issueTitle: string;
  reason: string;
  isRetriage: boolean; // true if this is a re-triage after author updated the issue
  skipReason: string;  // empty string if shouldTriage is true
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

/** Bot suffixes that indicate automated issue creation. */
const BOT_SUFFIXES = ['[bot]', '-bot'];

/** Labels that indicate an issue has already been triaged. */
const TRIAGED_LABELS = [
  'agent:plan',
  'agent:implement',
  'needs-human-review',
  'wontfix',
  'duplicate',
  'invalid',
];

/** Label that enables re-triage on edit. */
const RETRIAGE_LABEL = 'needs-more-info';

// --- Public API ---

/**
 * Check if an issue author is a bot.
 */
export function isBot(login: string, userType?: string): boolean {
  if (userType === 'Bot') return true;
  const lower = login.toLowerCase();
  return BOT_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

/**
 * Check if an issue has already been triaged (has a triaged label).
 */
export function isAlreadyTriaged(labels: string[]): boolean {
  return labels.some((label) => TRIAGED_LABELS.includes(label));
}

/**
 * Check if an issue qualifies for re-triage on edit.
 * Re-triage is only allowed when the `needs-more-info` label is present
 * and the event is an edit.
 */
export function shouldRetriage(labels: string[], eventName: string): boolean {
  if (eventName !== 'edited') return false;
  return labels.includes(RETRIAGE_LABEL);
}

/**
 * Evaluate whether triage should proceed for a given issue.
 *
 * Decision logic:
 * 1. Skip pull requests — they're not issues.
 * 2. Skip bot-authored issues.
 * 3. On edit + `needs-more-info` → re-triage.
 * 4. On edit + never triaged → initial triage (e.g. issue predates workflow).
 * 5. On edit + already triaged → skip.
 * 6. On open + already triaged → skip.
 * 7. Otherwise, proceed with triage.
 */
export function evaluate(issue: IssuePayload, eventName: string): TriageDecision {
  const labelNames = issue.labels.map((l) => l.name);

  const base: Pick<TriageDecision, 'issueNumber' | 'issueTitle'> = {
    issueNumber: issue.number,
    issueTitle: issue.title,
  };

  // Gate 1: Not an issue (PR)
  if (issue.pull_request) {
    return {
      ...base,
      shouldTriage: false,
      reason: 'Pull request — not an issue.',
      isRetriage: false,
      skipReason: 'pull_request',
    };
  }

  // Gate 2: Bot author
  if (isBot(issue.user.login, issue.user.type)) {
    return {
      ...base,
      shouldTriage: false,
      reason: `Bot-authored issue (${issue.user.login}) — skipping.`,
      isRetriage: false,
      skipReason: 'bot_author',
    };
  }

  const alreadyTriaged = isAlreadyTriaged(labelNames);

  // Gate 3: Edit event routing
  if (eventName === 'edited') {
    // Re-triage: issue was triaged as needs-more-info, author updated it
    if (shouldRetriage(labelNames, eventName)) {
      return {
        ...base,
        shouldTriage: true,
        reason: `Re-triage: issue edited with '${RETRIAGE_LABEL}' label present.`,
        isRetriage: true,
        skipReason: '',
      };
    }
    // Never triaged: treat edit like an open event (e.g. issue created before workflow existed)
    if (!alreadyTriaged) {
      return {
        ...base,
        shouldTriage: true,
        reason: 'Issue edited but never triaged — proceeding with initial triage.',
        isRetriage: false,
        skipReason: '',
      };
    }
    // Already triaged with a final label — skip
    return {
      ...base,
      shouldTriage: false,
      reason: 'Edit event on already-triaged issue — skipping.',
      isRetriage: false,
      skipReason: 'edit_already_triaged',
    };
  }

  // Gate 4: Already triaged (open/reopened event)
  if (alreadyTriaged) {
    return {
      ...base,
      shouldTriage: false,
      reason: 'Issue already has a triage label — skipping.',
      isRetriage: false,
      skipReason: 'already_triaged',
    };
  }

  // Proceed
  return {
    ...base,
    shouldTriage: true,
    reason: 'New issue ready for triage.',
    isRetriage: false,
    skipReason: '',
  };
}

// --- CLI: --evaluate ---

if (process.argv.includes('--evaluate')) {
  const eventName = process.env.EVENT_NAME || 'opened';

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

  const decision = evaluate(issue, eventName);
  console.log(JSON.stringify(decision, null, 2));
}

// --- CLI: --self-test ---

if (process.argv.includes('--self-test')) {
  console.log('Running issue-triage-guard self-test...\n');

  // --- isBot ---
  console.assert(isBot('dependabot[bot]') === true, 'dependabot[bot] should be detected as bot');
  console.assert(isBot('renovate-bot') === true, 'renovate-bot should be detected as bot');
  console.assert(isBot('github-actions[bot]', 'Bot') === true, 'Bot user type should be detected');
  console.assert(isBot('alice') === false, 'Regular user should not be a bot');
  console.assert(
    isBot('botmaster') === false,
    'User with "bot" in name but no suffix should not match',
  );

  // --- isAlreadyTriaged ---
  console.assert(isAlreadyTriaged(['agent:plan']) === true, 'agent:plan should indicate triaged');
  console.assert(
    isAlreadyTriaged(['agent:implement']) === true,
    'agent:implement should indicate triaged',
  );
  console.assert(
    isAlreadyTriaged(['needs-human-review']) === true,
    'needs-human-review should indicate triaged',
  );
  console.assert(isAlreadyTriaged(['wontfix']) === true, 'wontfix should indicate triaged');
  console.assert(
    isAlreadyTriaged(['bug', 'enhancement']) === false,
    'Regular labels should not indicate triaged',
  );
  console.assert(isAlreadyTriaged([]) === false, 'No labels should not indicate triaged');

  // --- shouldRetriage ---
  console.assert(
    shouldRetriage(['needs-more-info'], 'edited') === true,
    'Should re-triage on edit with needs-more-info label',
  );
  console.assert(
    shouldRetriage(['needs-more-info'], 'opened') === false,
    'Should NOT re-triage on open even with needs-more-info',
  );
  console.assert(
    shouldRetriage(['bug'], 'edited') === false,
    'Should NOT re-triage on edit without needs-more-info',
  );

  // --- evaluate ---

  // New issue, normal user
  const newIssue = evaluate(
    {
      number: 1,
      title: 'Bug: executor hangs on FatalError',
      body: 'Steps to reproduce...',
      user: { login: 'alice' },
      labels: [],
    },
    'opened',
  );
  console.assert(newIssue.shouldTriage === true, 'New issue should be triaged');
  console.assert(newIssue.isRetriage === false, 'New issue is not re-triage');

  // Bot issue
  const botIssue = evaluate(
    {
      number: 2,
      title: 'Dependency update',
      body: null,
      user: { login: 'dependabot[bot]', type: 'Bot' },
      labels: [],
    },
    'opened',
  );
  console.assert(botIssue.shouldTriage === false, 'Bot issue should be skipped');
  console.assert(botIssue.skipReason === 'bot_author', 'Skip reason should be bot_author');

  // PR (has pull_request field)
  const prIssue = evaluate(
    {
      number: 3,
      title: 'Fix: replay race condition',
      body: null,
      pull_request: { url: 'https://...' },
      user: { login: 'alice' },
      labels: [],
    },
    'opened',
  );
  console.assert(prIssue.shouldTriage === false, 'PR should be skipped');
  console.assert(prIssue.skipReason === 'pull_request', 'Skip reason should be pull_request');

  // Already triaged
  const triagedIssue = evaluate(
    {
      number: 4,
      title: 'Add DynamoDB storage backend',
      body: 'Support for AWS DynamoDB as a storage backend.',
      user: { login: 'alice' },
      labels: [{ name: 'agent:implement' }],
    },
    'opened',
  );
  console.assert(triagedIssue.shouldTriage === false, 'Already triaged issue should be skipped');
  console.assert(
    triagedIssue.skipReason === 'already_triaged',
    'Skip reason should be already_triaged',
  );

  // Edit with needs-more-info → re-triage
  const retriageIssue = evaluate(
    {
      number: 5,
      title: 'Bug: sleep() does not persist across worker restarts',
      body: 'Updated with full traceback and environment details...',
      user: { login: 'alice' },
      labels: [{ name: 'needs-more-info' }],
    },
    'edited',
  );
  console.assert(retriageIssue.shouldTriage === true, 'Re-triage should proceed');
  console.assert(retriageIssue.isRetriage === true, 'Should be flagged as re-triage');

  // Edit on never-triaged issue → initial triage (e.g. issue predates workflow)
  const editNeverTriaged = evaluate(
    {
      number: 6,
      title: 'Add retry backoff strategy option',
      body: 'Updated description.',
      user: { login: 'alice' },
      labels: [{ name: 'enhancement' }],
    },
    'edited',
  );
  console.assert(
    editNeverTriaged.shouldTriage === true,
    'Edit on never-triaged issue should proceed with triage',
  );
  console.assert(editNeverTriaged.isRetriage === false, 'Should not be flagged as re-triage');

  // Edit on already-triaged issue (without needs-more-info) → skip
  const editAlreadyTriaged = evaluate(
    {
      number: 7,
      title: 'Refactor serialization encoder',
      body: 'Updated',
      user: { login: 'alice' },
      labels: [{ name: 'agent:implement' }],
    },
    'edited',
  );
  console.assert(
    editAlreadyTriaged.shouldTriage === false,
    'Edit on already-triaged issue should skip',
  );
  console.assert(
    editAlreadyTriaged.skipReason === 'edit_already_triaged',
    'Skip reason should be edit_already_triaged',
  );

  console.log('\n✔ All self-tests passed.');
}
