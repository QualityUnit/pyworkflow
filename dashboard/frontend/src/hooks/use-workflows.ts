/**
 * React Query hooks for workflows.
 */

import { useQuery } from '@tanstack/react-query'
import { listWorkflows, getWorkflow } from '@/api'

export function useWorkflows() {
  return useQuery({
    queryKey: ['workflows'],
    queryFn: listWorkflows,
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

export function useWorkflow(name: string) {
  return useQuery({
    queryKey: ['workflow', name],
    queryFn: () => getWorkflow(name),
    enabled: !!name,
  })
}
