/**
 * Runs table component with TanStack React Table.
 */

import { useCallback, useEffect, useState, useRef } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { formatDistanceToNow } from 'date-fns'
import { MoreHorizontal, XCircle, ExternalLink, X, ChevronDown } from 'lucide-react'
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
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu'
import { DataTableColumnHeader } from '@/components/data-table/column-header'
import { DataTableViewOptions } from '@/components/data-table/view-options'
import { DataTablePagination } from '@/components/data-table/pagination'
import { StatusBadge } from './status-badge'
import { DateRangeFilter } from './date-range-filter'
import { useWorkflows } from '@/hooks/use-workflows'
import type { Run } from '@/api/types'
import type { DateRange, RunsFilters } from '@/features/runs'

interface RunsTableProps {
  runs: Run[]
  onPageChange?: (pageIndex: number) => void
  dateRange?: DateRange
  onDateRangeChange?: (range: DateRange) => void
  filters?: RunsFilters
  onFiltersChange?: (filters: RunsFilters) => void
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

export function RunsTable({
  runs,
  onPageChange,
  dateRange,
  onDateRangeChange,
  filters,
  onFiltersChange,
}: RunsTableProps) {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'started_at', desc: true },
  ])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 20,
  })

  // Local state for search input (to prevent re-renders while typing)
  const [localSearchQuery, setLocalSearchQuery] = useState('')
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Fetch workflows for the filter dropdown
  const { data: workflowsData } = useWorkflows()
  const workflowOptions = workflowsData?.items.map(w => ({
    label: w.name,
    value: w.name,
  })) ?? []

  // Local state for when no external state is provided
  const [localDateRange, setLocalDateRange] = useState<DateRange>({
    from: null,
    to: null,
  })
  const [localFilters, setLocalFilters] = useState<RunsFilters>({
    searchQuery: '',
    statusFilter: null,
    workflowFilter: null,
  })

  // Use external state if provided, otherwise use local state
  const effectiveDateRange = dateRange ?? localDateRange
  const handleDateRangeChange = onDateRangeChange ?? setLocalDateRange
  const effectiveFilters = filters ?? localFilters
  const handleFiltersChange = onFiltersChange ?? setLocalFilters

  // Sync local search with external filter when it changes externally
  useEffect(() => {
    setLocalSearchQuery(effectiveFilters.searchQuery)
  }, [effectiveFilters.searchQuery])

  // Notify parent of page changes
  useEffect(() => {
    onPageChange?.(pagination.pageIndex)
  }, [pagination.pageIndex, onPageChange])

  const handleRowClick = useCallback(
    (runId: string) => {
      navigate({ to: '/runs/$runId', params: { runId } })
    },
    [navigate]
  )

  const handleCancelRun = useCallback((runId: string) => {
    toast.info('Cancel run feature coming soon', {
      description: `Run ${runId.slice(0, 16)}... will be cancelled when this feature is implemented.`,
    })
  }, [])

  // Debounced search - update parent filter after user stops typing
  const handleSearchInputChange = useCallback((value: string) => {
    setLocalSearchQuery(value)

    // Clear existing timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
    }

    // Set new timeout to update filter after 500ms of no typing
    searchTimeoutRef.current = setTimeout(() => {
      handleFiltersChange({
        ...effectiveFilters,
        searchQuery: value,
      })
    }, 500)
  }, [effectiveFilters, handleFiltersChange])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current)
      }
    }
  }, [])

  const handleStatusFilterChange = useCallback((value: string) => {
    handleFiltersChange({
      ...effectiveFilters,
      statusFilter: value === 'all' ? null : value,
    })
  }, [effectiveFilters, handleFiltersChange])

  const handleWorkflowFilterChange = useCallback((value: string) => {
    handleFiltersChange({
      ...effectiveFilters,
      workflowFilter: value === 'all' ? null : value,
    })
  }, [effectiveFilters, handleFiltersChange])

  const handleClearFilters = useCallback(() => {
    setLocalSearchQuery('')
    handleFiltersChange({
      searchQuery: '',
      statusFilter: null,
      workflowFilter: null,
    })
  }, [handleFiltersChange])

  const hasActiveFilters = effectiveFilters.searchQuery || effectiveFilters.statusFilter || effectiveFilters.workflowFilter

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
            {runId}
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
    },
    {
      accessorKey: 'status',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Status" />
      ),
      cell: ({ row }) => <StatusBadge status={row.getValue('status')} />,
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
    data: runs,
    columns,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
      pagination,
    },
    enableRowSelection: true,
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  // Count selected rows
  const selectedCount = Object.keys(rowSelection).length

  return (
    <div className="flex flex-1 flex-col gap-4 h-full">
      {/* Custom toolbar with server-side filtering */}
      <div className="flex items-center gap-4">
        <div className="flex flex-1 flex-col-reverse items-start gap-y-2 sm:flex-row sm:items-center sm:space-x-2">
          <Input
            placeholder="Search runs..."
            value={localSearchQuery}
            onChange={(e) => handleSearchInputChange(e.target.value)}
            className="h-8 w-[150px] lg:w-[250px]"
          />
          <div className="flex gap-x-2">
            {/* Status filter dropdown - single select */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="h-8">
                  Status
                  {effectiveFilters.statusFilter && (
                    <Badge variant="secondary" className="ml-2 rounded-sm px-1 font-normal">
                      1
                    </Badge>
                  )}
                  <ChevronDown className="ml-2 h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-[180px]">
                <DropdownMenuRadioGroup
                  value={effectiveFilters.statusFilter ?? 'all'}
                  onValueChange={handleStatusFilterChange}
                >
                  <DropdownMenuRadioItem value="all">
                    All statuses
                  </DropdownMenuRadioItem>
                  <DropdownMenuSeparator />
                  {statusOptions.map((option) => (
                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                      {option.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Workflow filter dropdown - single select */}
            {workflowOptions.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-8">
                    Workflow
                    {effectiveFilters.workflowFilter && (
                      <Badge variant="secondary" className="ml-2 rounded-sm px-1 font-normal">
                        1
                      </Badge>
                    )}
                    <ChevronDown className="ml-2 h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-[200px] max-h-[300px] overflow-y-auto">
                  <DropdownMenuRadioGroup
                    value={effectiveFilters.workflowFilter ?? 'all'}
                    onValueChange={handleWorkflowFilterChange}
                  >
                    <DropdownMenuRadioItem value="all">
                      All workflows
                    </DropdownMenuRadioItem>
                    <DropdownMenuSeparator />
                    {workflowOptions.map((option) => (
                      <DropdownMenuRadioItem key={option.value} value={option.value}>
                        {option.label}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              onClick={handleClearFilters}
              className="h-8 px-2 lg:px-3"
            >
              Reset
              <X className="ml-2 h-4 w-4" />
            </Button>
          )}
        </div>
        <DataTableViewOptions table={table} />
        <DateRangeFilter value={effectiveDateRange} onChange={handleDateRangeChange} />
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
