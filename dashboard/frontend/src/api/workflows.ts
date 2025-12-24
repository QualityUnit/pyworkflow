/**
 * API functions for workflows.
 */

import { api } from './client'
import type { WorkflowListResponse, Workflow } from './types'

export async function listWorkflows(): Promise<WorkflowListResponse> {
  return api.get<WorkflowListResponse>('/api/v1/workflows')
}

export async function getWorkflow(name: string): Promise<Workflow> {
  return api.get<Workflow>(`/api/v1/workflows/${name}`)
}
