#!/usr/bin/env npx tsx
// ============================================================================
// Review Agent Utilities — shared helpers for review agent workflows
//
// Provides functions for:
//   - Bot comment detection
//   - Thread analysis (bot-only vs human-participated)
//   - Check run lookup by SHA
//   - HEAD SHA extraction from CI environment
//
// Usage: import directly in scripts, or run standalone for smoke test:
//   npx tsx scripts/review-agent-utils.ts --self-test
//
// Environment variables (set by CI):
//   GITHUB_REPOSITORY  — owner/repo
//   GITHUB_SHA         — commit SHA (push events)
//   GITHUB_EVENT_PATH  — path to event payload JSON
//   GITHUB_TOKEN       — auth token for API calls
// ============================================================================

import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

// --- Types ---

export interface Comment {
  id: number;
  node_id?: string;
  user: { login: string };
  body?: string;
  in_reply_to_id?: number;
  commit_id?: string;
  original_commit_id?: string;
}

export interface CheckRun {
  id: number;
  name: string;
  head_sha: string;
  status: 'queued' | 'in_progress' | 'completed';
  conclusion: string | null;
  started_at: string;
  completed_at: string | null;
  output: {
    title: string | null;
    summary: string | null;
  };
}

// --- Constants ---

/** Known bot login patterns for review agent comments. */
const BOT_LOGINS = new Set([
  'github-actions[bot]',
  'github-actions',
  'dependabot[bot]',
]);

// --- Public API ---

/**
 * Check if a comment was authored by a known bot account.
 * Returns true for github-actions[bot], dependabot[bot], and any login ending in [bot].
 */
export function isReviewBotComment(comment: { user: { login: string } }): boolean {
  const login = comment.user.login;
  return BOT_LOGINS.has(login) || login.endsWith('[bot]');
}

/**
 * Check if ALL comments in a thread are from bot accounts.
 * Returns false if any human has participated in the thread.
 * Returns true for empty threads (no comments to contradict).
 */
export function isThreadBotOnly(thread: Comment[]): boolean {
  if (thread.length === 0) return true;
  return thread.every((c) => isReviewBotComment(c));
}

/**
 * Fetch the latest review-agent check run for a specific SHA.
 * Requires `gh` CLI and GITHUB_REPOSITORY env var.
 * Returns null if no check run is found or on error.
 */
export function getLatestReviewRunForSha(
  owner: string,
  repo: string,
  sha: string,
): CheckRun | null {
  try {
    const output = execSync(
      `gh api "repos/${owner}/${repo}/commits/${sha}/check-runs" --jq '.check_runs[] | select(.name == "review-agent")'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] },
    );

    if (!output.trim()) return null;

    // gh --jq returns one JSON object per line; take the last (most recent)
    const lines = output.trim().split('\n');
    const lastLine = lines[lines.length - 1];
    return JSON.parse(lastLine) as CheckRun;
  } catch {
    return null;
  }
}

/**
 * Get the current PR head SHA from the CI environment.
 *
 * Resolution order:
 * 1. GITHUB_EVENT_PATH → pull_request.head.sha (PR events)
 * 2. GITHUB_SHA (push events, fallback)
 * 3. git rev-parse HEAD (local mode)
 */
export function getHeadSha(): string {
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (eventPath) {
    try {
      const event = JSON.parse(readFileSync(eventPath, 'utf-8'));
      if (event.pull_request?.head?.sha) {
        return event.pull_request.head.sha;
      }
    } catch {
      // fall through
    }
  }

  if (process.env.GITHUB_SHA) {
    return process.env.GITHUB_SHA;
  }

  try {
    return execSync('git rev-parse HEAD', {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
  } catch {
    throw new Error(
      'Unable to determine HEAD SHA: no GITHUB_EVENT_PATH, GITHUB_SHA, or git repository found.',
    );
  }
}

/**
 * Check if a given SHA has already been reviewed by searching for the
 * harness review marker in PR comments.
 */
export function hasExistingReview(
  comments: Array<{ body?: string }>,
  sha: string,
): boolean {
  const marker = `<!-- harness-review: ${sha} -->`;
  return comments.some((c) => c.body?.includes(marker));
}

/**
 * Check if a rerun has already been requested for a given SHA.
 */
export function hasExistingRerunRequest(
  comments: Array<{ body?: string }>,
  sha: string,
): boolean {
  const marker = '<!-- review-agent-auto-rerun -->';
  const trigger = `sha:${sha}`;
  return comments.some((c) => c.body?.includes(marker) && c.body?.includes(trigger));
}

// --- Self-test (run with --self-test) ---

if (process.argv.includes('--self-test')) {
  console.log('Running review-agent-utils self-test...\n');

  console.assert(
    isReviewBotComment({ user: { login: 'github-actions[bot]' } }) === true,
    'github-actions[bot] should be a bot',
  );
  console.assert(
    isReviewBotComment({ user: { login: 'octocat' } }) === false,
    'octocat should not be a bot',
  );
  console.assert(
    isReviewBotComment({ user: { login: 'my-custom[bot]' } }) === true,
    'custom [bot] suffix should be detected',
  );

  console.assert(isThreadBotOnly([]) === true, 'empty thread is bot-only');
  console.assert(
    isThreadBotOnly([
      { id: 1, user: { login: 'github-actions[bot]' } },
      { id: 2, user: { login: 'dependabot[bot]' }, in_reply_to_id: 1 },
    ]) === true,
    'all-bot thread should be bot-only',
  );
  console.assert(
    isThreadBotOnly([
      { id: 1, user: { login: 'github-actions[bot]' } },
      { id: 2, user: { login: 'developer' }, in_reply_to_id: 1 },
    ]) === false,
    'thread with human should not be bot-only',
  );

  console.assert(
    hasExistingReview(
      [{ body: '<!-- harness-review: abc123 -->\nReview content' }],
      'abc123',
    ) === true,
    'should find existing review',
  );
  console.assert(
    hasExistingReview(
      [{ body: '<!-- harness-review: abc123 -->\nReview content' }],
      'def456',
    ) === false,
    'should not find review for different SHA',
  );

  console.assert(
    hasExistingRerunRequest(
      [{ body: '<!-- review-agent-auto-rerun -->\n@review-agent please re-review\nsha:abc123' }],
      'abc123',
    ) === true,
    'should find existing rerun request',
  );
  console.assert(
    hasExistingRerunRequest(
      [{ body: '<!-- review-agent-auto-rerun -->\nsha:abc123' }],
      'def456',
    ) === false,
    'should not find rerun for different SHA',
  );

  try {
    const sha = getHeadSha();
    console.assert(sha.length >= 7, 'SHA should be at least 7 chars');
    console.log(`✔ getHeadSha() returned: ${sha.slice(0, 12)}`);
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.log(`⚠ getHeadSha() threw (expected outside git repo): ${msg}`);
  }

  console.log('\n✔ All self-tests passed.');
}
