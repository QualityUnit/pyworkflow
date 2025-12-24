/**
 * API functions for workflow runs.
 */

import { api } from './client'
import type {
  RunListResponse,
  RunDetail,
  EventListResponse,
  StepListResponse,
  HookListResponse,
} from './types'

export interface ListRunsParams {
  workflow_name?: string
  status?: string
  limit?: number
  offset?: number
}

export async function listRuns(params: ListRunsParams = {}): Promise<RunListResponse> {
  const searchParams = new URLSearchParams()

  if (params.workflow_name) {
    searchParams.set('workflow_name', params.workflow_name)
  }
  if (params.status) {
    searchParams.set('status', params.status)
  }
  if (params.limit !== undefined) {
    searchParams.set('limit', params.limit.toString())
  }
  if (params.offset !== undefined) {
    searchParams.set('offset', params.offset.toString())
  }

  const query = searchParams.toString()
  const path = query ? `/api/v1/runs?${query}` : '/api/v1/runs'

  return api.get<RunListResponse>(path)
}

export async function getRun(runId: string): Promise<RunDetail> {
  return api.get<RunDetail>(`/api/v1/runs/${runId}`)
}

export async function getRunEvents(runId: string): Promise<EventListResponse> {
  return api.get<EventListResponse>(`/api/v1/runs/${runId}/events`)
}

export async function getRunSteps(runId: string): Promise<StepListResponse> {
  return api.get<StepListResponse>(`/api/v1/runs/${runId}/steps`)
}

export async function getRunHooks(runId: string): Promise<HookListResponse> {
  return api.get<HookListResponse>(`/api/v1/runs/${runId}/hooks`)
}
