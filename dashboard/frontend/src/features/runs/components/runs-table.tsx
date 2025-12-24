/**
 * Runs table component.
 */

import { Link } from '@tanstack/react-router'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatusBadge } from './status-badge'
import type { Run } from '@/api/types'

interface RunsTableProps {
  runs: Run[]
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '-'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString()
}

export function RunsTable({ runs }: RunsTableProps) {
  if (runs.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No workflow runs found.
      </div>
    )
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Run ID</TableHead>
            <TableHead>Workflow</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Duration</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.run_id}>
              <TableCell className="font-mono text-sm">
                <Link
                  to="/runs/$runId"
                  params={{ runId: run.run_id }}
                  className="text-primary hover:underline"
                >
                  {run.run_id.slice(0, 16)}...
                </Link>
              </TableCell>
              <TableCell>{run.workflow_name}</TableCell>
              <TableCell>
                <StatusBadge status={run.status} />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatDate(run.created_at)}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatDuration(run.duration_seconds)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
