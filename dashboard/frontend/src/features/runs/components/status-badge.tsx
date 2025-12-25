/**
 * Status badge component for workflow run status.
 */

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { RunStatus } from '@/api/types'

interface StatusBadgeProps {
  status: RunStatus | string
}

const statusConfig: Record<string, { className: string; label: string }> = {
  pending: {
    className: 'bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-300',
    label: 'Pending',
  },
  running: {
    className: 'bg-blue-100 text-blue-700 hover:bg-blue-100 dark:bg-blue-900 dark:text-blue-300',
    label: 'Running',
  },
  suspended: {
    className: 'bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-900 dark:text-amber-300',
    label: 'Suspended',
  },
  completed: {
    className: 'bg-green-100 text-green-700 hover:bg-green-100 dark:bg-green-900 dark:text-green-300',
    label: 'Completed',
  },
  failed: {
    className: 'bg-red-100 text-red-700 hover:bg-red-100 dark:bg-red-900 dark:text-red-300',
    label: 'Failed',
  },
  interrupted: {
    className: 'bg-orange-100 text-orange-700 hover:bg-orange-100 dark:bg-orange-900 dark:text-orange-300',
    label: 'Interrupted',
  },
  cancelled: {
    className: 'bg-slate-100 text-slate-600 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400',
    label: 'Cancelled',
  },
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    label: status,
  }

  return (
    <Badge variant="outline" className={cn('capitalize border-0', config.className)}>
      {config.label}
    </Badge>
  )
}
