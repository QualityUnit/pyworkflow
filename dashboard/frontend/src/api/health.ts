/**
 * API functions for health check.
 */

import { api } from './client'
import type { HealthResponse } from './types'

export async function checkHealth(): Promise<HealthResponse> {
  return api.get<HealthResponse>('/api/v1/health')
}
