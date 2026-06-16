/**
 * React Query hooks for workflow runs.
 */

import { useQuery, useInfiniteQuery, keepPreviousData } from '@tanstack/react-query'
import {
  listRuns,
  getRun,
  getRunEvents,
  type ListRunsParams,
} from '@/api'
import type { RunDetail, RunStatus } from '@/api/types'

// Refresh intervals in milliseconds
export const REFRESH_INTERVAL = 30000 // 30 seconds for completed workflows
export const ACTIVE_REFRESH_INTERVAL = 10000 // 10 seconds for active workflows

// Statuses that indicate a workflow is still active
const ACTIVE_STATUSES: RunStatus[] = ['pending', 'running', 'suspended']

/**
 * Check if a run status indicates the workflow is active.
 */
export function isActiveStatus(status: RunStatus | undefined): boolean {
  return !!status && ACTIVE_STATUSES.includes(status)
}

interface UseRunsOptions {
  params?: ListRunsParams
  autoRefresh?: boolean
}

export function useRuns({ params = {}, autoRefresh = true }: UseRunsOptions = {}) {
  return useQuery({
    queryKey: ['runs', params],
    queryFn: () => listRuns(params),
    refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
}

/**
 * Cursor-paginated runs list. Each page fetches a bounded number of summary rows (see `limit` in
 * params) and follows `next_cursor` for subsequent pages, so the Runs page never fetches the whole
 * table at once (issue #482). Auto-refresh only re-fetches already-loaded pages.
 */
export function useRunsInfinite({ params = {}, autoRefresh = true }: UseRunsOptions = {}) {
  return useInfiniteQuery({
    queryKey: ['runs-infinite', params],
    queryFn: ({ pageParam }) =>
      listRuns({ ...params, cursor: pageParam as string | undefined }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
    refetchOnWindowFocus: false,
  })
}

interface UseRunOptions {
  autoRefresh?: boolean
}

export function useRun(runId: string, { autoRefresh = true }: UseRunOptions = {}) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId),
    enabled: !!runId,
    refetchInterval: (query) => {
      if (!autoRefresh) return false
      // Use faster polling for active workflows
      const data = query.state.data as RunDetail | undefined
      return isActiveStatus(data?.status) ? ACTIVE_REFRESH_INTERVAL : REFRESH_INTERVAL
    },
    refetchOnWindowFocus: false,
  })
}

interface UseRunEventsOptions {
  autoRefresh?: boolean
  runStatus?: RunStatus
}

export function useRunEvents(
  runId: string,
  { autoRefresh = true, runStatus }: UseRunEventsOptions = {}
) {
  return useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => getRunEvents(runId),
    enabled: !!runId,
    refetchInterval: () => {
      if (!autoRefresh) return false
      // Use faster polling for active workflows
      return isActiveStatus(runStatus) ? ACTIVE_REFRESH_INTERVAL : REFRESH_INTERVAL
    },
    refetchOnWindowFocus: false,
  })
}
