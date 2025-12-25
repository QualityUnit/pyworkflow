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

export function useRuns(params: ListRunsParams = {}) {
  return useQuery({
    queryKey: ['runs', params],
    queryFn: () => listRuns(params),
    refetchInterval: 5000, // Refresh every 5 seconds
  })
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId),
    enabled: !!runId,
    refetchInterval: 5000,
  })
}

export function useRunEvents(runId: string) {
  return useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => getRunEvents(runId),
    enabled: !!runId,
    refetchInterval: 5000,
  })
}
