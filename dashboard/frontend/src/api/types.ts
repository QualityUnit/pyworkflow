/**
 * TypeScript types for PyWorkflow Dashboard API.
 */

// Run statuses
export type RunStatus =
  | 'pending'
  | 'running'
  | 'suspended'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'cancelled'

// Workflow types
export interface WorkflowParameter {
  name: string
  type: 'string' | 'number' | 'boolean' | 'array' | 'object' | 'any'
  required: boolean
  default: unknown
}

export interface Workflow {
  name: string
  description: string | null
  max_duration: string | null
  tags: string[]
  parameters: WorkflowParameter[]
}

export interface WorkflowListResponse {
  items: Workflow[]
  count: number
}

// Run types
export interface Run {
  run_id: string
  workflow_name: string
  status: RunStatus
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error: string | null
  recovery_attempts: number
}

export interface RunDetail extends Run {
  input_args: unknown
  input_kwargs: unknown
  result: unknown
  metadata: Record<string, unknown>
  max_duration: string | null
  max_recovery_attempts: number
}

export interface RunListResponse {
  items: Run[]
  count: number
  limit: number
  next_cursor: string | null
}

// Event types
export interface Event {
  event_id: string
  run_id: string
  type: string
  timestamp: string
  sequence: number | null
  data: Record<string, unknown>
}

export interface EventListResponse {
  items: Event[]
  count: number
}

// Step types
export interface Step {
  step_id: string
  run_id: string
  step_name: string
  status: string
  attempt: number
  max_retries: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  error: string | null
}

export interface StepListResponse {
  items: Step[]
  count: number
}

// Hook types
export interface Hook {
  hook_id: string
  run_id: string
  name: string | null
  status: string
  created_at: string
  received_at: string | null
  expires_at: string | null
  has_payload: boolean
}

export interface HookListResponse {
  items: Hook[]
  count: number
}

// Health check
export interface HealthResponse {
  status: string
  storage_healthy: boolean
}

// Start run types
export interface StartRunRequest {
  workflow_name: string
  kwargs: Record<string, unknown>
}

export interface StartRunResponse {
  run_id: string
  workflow_name: string
}
