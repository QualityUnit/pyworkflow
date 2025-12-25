/**
 * React Query hooks for workflow runs.
 */

import { useQuery } from '@tanstack/react-query'
import {
  listRuns,
  getRun,
  getRunEvents,
  type ListRunsParams,
} from '@/api'

// Refresh interval in milliseconds
export const REFRESH_INTERVAL = 30000 // 30 seconds

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
    refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
    refetchOnWindowFocus: false,
  })
}

export function useRunEvents(runId: string, { autoRefresh = true }: UseRunOptions = {}) {
  return useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => getRunEvents(runId),
    enabled: !!runId,
    refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
    refetchOnWindowFocus: false,
  })
}
