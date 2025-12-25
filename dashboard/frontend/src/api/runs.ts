/**
 * API functions for workflow runs.
 */

import { api } from './client'
import type {
  RunListResponse,
  RunDetail,
  EventListResponse,
  StartRunRequest,
  StartRunResponse,
} from './types'

export interface ListRunsParams {
  query?: string
  status?: string
  start_time?: string  // ISO 8601 datetime
  end_time?: string    // ISO 8601 datetime
  limit?: number
  cursor?: string
}

export async function listRuns(params: ListRunsParams = {}): Promise<RunListResponse> {
  const searchParams = new URLSearchParams()

  if (params.query) {
    searchParams.set('query', params.query)
  }
  if (params.status) {
    searchParams.set('status', params.status)
  }
  if (params.start_time) {
    searchParams.set('start_time', params.start_time)
  }
  if (params.end_time) {
    searchParams.set('end_time', params.end_time)
  }
  if (params.limit !== undefined) {
    searchParams.set('limit', params.limit.toString())
  }
  if (params.cursor) {
    searchParams.set('cursor', params.cursor)
  }

  const queryString = searchParams.toString()
  const path = queryString ? `/api/v1/runs?${queryString}` : '/api/v1/runs'

  return api.get<RunListResponse>(path)
}

export async function getRun(runId: string): Promise<RunDetail> {
  return api.get<RunDetail>(`/api/v1/runs/${runId}`)
}

export async function getRunEvents(runId: string): Promise<EventListResponse> {
  return api.get<EventListResponse>(`/api/v1/runs/${runId}/events`)
}

export async function startRun(request: StartRunRequest): Promise<StartRunResponse> {
  return api.post<StartRunResponse>('/api/v1/runs', request)
}

/**
 * Cancel a running workflow.
 * TODO: Implement when backend supports cancellation.
 */
export async function cancelRun(_runId: string): Promise<void> {
  // TODO: Implement when backend supports cancellation
  // return api.post<void>(`/api/v1/runs/${runId}/cancel`)
  throw new Error('Cancel run not yet implemented')
}
