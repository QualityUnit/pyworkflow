/**
 * React Query hooks for health check.
 */

import { useQuery } from '@tanstack/react-query'
import { checkHealth } from '@/api'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: checkHealth,
    refetchInterval: 10000, // Refresh every 10 seconds
  })
}
