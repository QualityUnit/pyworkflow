/**
 * Runs table component with TanStack React Table.
 */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  type ColumnDef,
  type ColumnFiltersState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { formatDistanceToNow } from 'date-fns'
import { MoreHorizontal, XCircle, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { DataTableColumnHeader } from '@/components/data-table/column-header'
import { DataTableToolbar } from '@/components/data-table/toolbar'
import { DataTablePagination } from '@/components/data-table/pagination'
import { StatusBadge } from './status-badge'
import { DateRangeFilter } from './date-range-filter'
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

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

// Status options for filtering
const statusOptions = [
  { label: 'Pending', value: 'pending' },
  { label: 'Running', value: 'running' },
  { label: 'Suspended', value: 'suspended' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
  { label: 'Interrupted', value: 'interrupted' },
  { label: 'Cancelled', value: 'cancelled' },
]

export function RunsTable({ runs }: RunsTableProps) {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'started_at', desc: true },
  ])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [dateRange, setDateRange] = useState<{ from: Date | null; to: Date | null }>({
    from: null,
    to: null,
  })

  const handleRowClick = useCallback(
    (runId: string) => {
      navigate({ to: '/runs/$runId', params: { runId } })
    },
    [navigate]
  )

  const handleCancelRun = useCallback((runId: string) => {
    // TODO: Implement cancel run API
    toast.info('Cancel run feature coming soon', {
      description: `Run ${runId.slice(0, 16)}... will be cancelled when this feature is implemented.`,
    })
  }, [])

  // Filter runs by date range
  const filteredRuns = useMemo(() => {
    if (!dateRange.from && !dateRange.to) return runs

    return runs.filter((run) => {
      if (!run.started_at) return false
      const startedAt = new Date(run.started_at)

      if (dateRange.from && startedAt < dateRange.from) return false
      if (dateRange.to) {
        const endOfDay = new Date(dateRange.to)
        endOfDay.setHours(23, 59, 59, 999)
        if (startedAt > endOfDay) return false
      }

      return true
    })
  }, [runs, dateRange])

  // Extract unique workflows for filtering
  const uniqueWorkflows = useMemo(() => {
    const workflowSet = new Set<string>()
    runs.forEach((r) => workflowSet.add(r.workflow_name))
    return Array.from(workflowSet)
      .sort()
      .map((name) => ({ label: name, value: name }))
  }, [runs])

  const columns: ColumnDef<Run>[] = [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() && 'indeterminate')
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Select all"
          className="translate-y-[2px]"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Select row"
          className="translate-y-[2px]"
          onClick={(e) => e.stopPropagation()}
        />
      ),
      enableSorting: false,
      enableHiding: false,
      meta: {
        className: 'w-[40px] pl-4',
      },
    },
    {
      accessorKey: 'run_id',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Run ID" />
      ),
      cell: ({ row }) => {
        const runId = row.getValue('run_id') as string
        return (
          <span className="font-mono text-sm">
            {runId.slice(0, 16)}...
          </span>
        )
      },
      enableHiding: false,
    },
    {
      accessorKey: 'workflow_name',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Workflow" />
      ),
      cell: ({ row }) => {
        const workflowName = row.getValue('workflow_name') as string
        return (
          <button
            onClick={(e) => {
              e.stopPropagation()
              navigate({ to: '/workflows/$name', params: { name: workflowName } })
            }}
            className="text-primary hover:underline flex items-center gap-1"
          >
            {workflowName}
            <ExternalLink className="h-3 w-3" />
          </button>
        )
      },
      filterFn: (row, id, value) => {
        return value.includes(row.getValue(id))
      },
    },
    {
      accessorKey: 'status',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Status" />
      ),
      cell: ({ row }) => <StatusBadge status={row.getValue('status')} />,
      filterFn: (row, id, value) => {
        return value.includes(row.getValue(id))
      },
    },
    {
      accessorKey: 'started_at',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Started" />
      ),
      cell: ({ row }) => {
        const startedAt = row.getValue('started_at') as string | null
        if (!startedAt) return <span className="text-muted-foreground">-</span>
        return (
          <span
            className="text-sm text-muted-foreground"
            title={formatDate(startedAt)}
          >
            {formatDistanceToNow(new Date(startedAt), { addSuffix: true })}
          </span>
        )
      },
    },
    {
      accessorKey: 'duration_seconds',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Duration" />
      ),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDuration(row.getValue('duration_seconds'))}
        </span>
      ),
    },
    {
      id: 'actions',
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => {
        const run = row.original
        const canCancel = ['pending', 'running', 'suspended'].includes(run.status)

        return (
          <div className="flex justify-end">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="h-8 w-8 p-0"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span className="sr-only">Open menu</span>
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Actions</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    handleRowClick(run.run_id)
                  }}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  View Details
                </DropdownMenuItem>
                {canCancel && (
                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCancelRun(run.run_id)
                    }}
                    className="text-destructive focus:text-destructive"
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    Cancel Run
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )
      },
      enableSorting: false,
      enableHiding: false,
      meta: {
        className: 'w-[50px]',
      },
    },
  ]

  const table = useReactTable({
    data: filteredRuns,
    columns,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
    },
    enableRowSelection: true,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    initialState: {
      pagination: {
        pageSize: 20,
      },
    },
  })

  // Build filters
  const filters = useMemo(() => {
    const result = []
    if (uniqueWorkflows.length > 0) {
      result.push({
        columnId: 'workflow_name',
        title: 'Workflow',
        options: uniqueWorkflows,
      })
    }
    result.push({
      columnId: 'status',
      title: 'Status',
      options: statusOptions,
    })
    return result
  }, [uniqueWorkflows])

  // Count selected rows
  const selectedCount = Object.keys(rowSelection).length

  return (
    <div className="flex flex-1 flex-col gap-4 h-full">
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <DataTableToolbar
            table={table}
            searchKey="run_id"
            searchPlaceholder="Search by run ID..."
            filters={filters}
          />
        </div>
        <DateRangeFilter value={dateRange} onChange={setDateRange} />
      </div>

      {selectedCount > 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{selectedCount} run(s) selected</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setRowSelection({})}
          >
            Clear selection
          </Button>
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0">
        <div className="overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const meta = header.column.columnDef.meta as { className?: string } | undefined
                    return (
                      <TableHead
                        key={header.id}
                        colSpan={header.colSpan}
                        className={meta?.className}
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    )
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows?.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && 'selected'}
                    className="cursor-pointer"
                    onClick={() => handleRowClick(row.original.run_id)}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as { className?: string } | undefined
                      return (
                        <TableCell key={cell.id} className={`py-3 ${meta?.className || ''}`}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="h-24 text-center"
                  >
                    No workflow runs found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <DataTablePagination table={table} className="mt-auto" />
    </div>
  )
}
