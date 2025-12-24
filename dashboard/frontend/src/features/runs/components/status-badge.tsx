/**
 * Status badge component for workflow run status.
 */

import { Badge } from '@/components/ui/badge'
import type { RunStatus } from '@/api/types'

interface StatusBadgeProps {
  status: RunStatus | string
}

const statusConfig: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  pending: { variant: 'secondary', label: 'Pending' },
  running: { variant: 'default', label: 'Running' },
  suspended: { variant: 'outline', label: 'Suspended' },
  completed: { variant: 'default', label: 'Completed' },
  failed: { variant: 'destructive', label: 'Failed' },
  interrupted: { variant: 'destructive', label: 'Interrupted' },
  cancelled: { variant: 'secondary', label: 'Cancelled' },
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] || { variant: 'secondary' as const, label: status }

  return (
    <Badge variant={config.variant} className="capitalize">
      {config.label}
    </Badge>
  )
}
