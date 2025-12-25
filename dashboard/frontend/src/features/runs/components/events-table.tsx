/**
 * Events table component with TanStack React Table for run event history.
 */

import { useMemo, useState, useCallback, useEffect } from 'react'
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  type VisibilityState,
  type ExpandedState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getSortedRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { formatDistanceToNow, format } from 'date-fns'
import { ChevronDown, ChevronRight } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTableColumnHeader } from '@/components/data-table/column-header'
import { DataTableToolbar } from '@/components/data-table/toolbar'
import type { Event } from '@/api/types'

interface EventsTableProps {
  events: Event[]
  initialStepFilter?: string[]
  initialEventTypeFilter?: string[]
  onFiltersChange?: (stepFilters: string[], eventTypeFilters: string[]) => void
}

// Get badge variant based on event type
function getEventBadgeVariant(type: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (type.includes('FAILED') || type.includes('ERROR')) return 'destructive'
  if (type.includes('COMPLETED') || type.includes('SUCCESS')) return 'default'
  if (type.includes('STARTED') || type.includes('CREATED')) return 'secondary'
  return 'outline'
}

// Format event type for display
function formatEventType(type: string): string {
  return type
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (l) => l.toUpperCase())
}

// Format duration in human readable form
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(1)
  return `${minutes}m ${seconds}s`
}

export function EventsTable({
  events,
  initialStepFilter = [],
  initialEventTypeFilter = [],
  onFiltersChange,
}: EventsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'sequence', desc: false },
  ])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [expanded, setExpanded] = useState<ExpandedState>({})

  // Apply initial filters when they change
  useEffect(() => {
    const newFilters: ColumnFiltersState = []
    if (initialStepFilter.length > 0) {
      newFilters.push({ id: 'step_name', value: initialStepFilter })
    }
    if (initialEventTypeFilter.length > 0) {
      newFilters.push({ id: 'type', value: initialEventTypeFilter })
    }
    setColumnFilters(newFilters)
  }, [initialStepFilter, initialEventTypeFilter])

  // Notify parent when filters change
  const handleColumnFiltersChange = useCallback(
    (updaterOrValue: ColumnFiltersState | ((old: ColumnFiltersState) => ColumnFiltersState)) => {
      setColumnFilters((prev) => {
        const newFilters = typeof updaterOrValue === 'function' ? updaterOrValue(prev) : updaterOrValue
        if (onFiltersChange) {
          const stepFilter = newFilters.find((f) => f.id === 'step_name')
          const typeFilter = newFilters.find((f) => f.id === 'type')
          onFiltersChange(
            (stepFilter?.value as string[]) || [],
            (typeFilter?.value as string[]) || []
          )
        }
        return newFilters
      })
    },
    [onFiltersChange]
  )

  // Extract unique event types for filtering (limit to 5)
  const uniqueEventTypes = useMemo(() => {
    const typeSet = new Set<string>()
    events.forEach((e) => typeSet.add(e.type))
    return Array.from(typeSet)
      .sort()
      .slice(0, 5)
      .map((type) => ({ label: formatEventType(type), value: type }))
  }, [events])

  // Extract unique step names for filtering (limit to 5)
  const uniqueStepNames = useMemo(() => {
    const stepSet = new Set<string>()
    events.forEach((e) => {
      if (e.data?.step_name) {
        stepSet.add(e.data.step_name as string)
      }
    })
    return Array.from(stepSet)
      .sort()
      .slice(0, 5)
      .map((name) => ({ label: name, value: name }))
  }, [events])

  // Calculate duration for completed events by finding corresponding started event
  const getDuration = useCallback((event: Event): number | null => {
    const type = event.type
    const eventSeq = event.sequence ?? 0

    // Only calculate for completed events
    if (type === 'step.completed') {
      const stepId = event.data?.step_id
      if (!stepId) return null

      // Find the most recent step.started with the same step_id before this event
      const startedEvent = events
        .filter(e =>
          e.type === 'step.started' &&
          e.data?.step_id === stepId &&
          (e.sequence ?? 0) < eventSeq
        )
        .sort((a, b) => (b.sequence ?? 0) - (a.sequence ?? 0))[0]

      if (startedEvent) {
        const start = new Date(startedEvent.timestamp).getTime()
        const end = new Date(event.timestamp).getTime()
        return end - start
      }
    } else if (type === 'workflow.completed') {
      // Find the most recent workflow.started before this event
      const startedEvent = events
        .filter(e =>
          e.type === 'workflow.started' &&
          (e.sequence ?? 0) < eventSeq
        )
        .sort((a, b) => (b.sequence ?? 0) - (a.sequence ?? 0))[0]

      if (startedEvent) {
        const start = new Date(startedEvent.timestamp).getTime()
        const end = new Date(event.timestamp).getTime()
        return end - start
      }
    }

    return null
  }, [events])

  // Get the corresponding start event for a completed event
  const getStartEvent = useCallback((event: Event): Event | null => {
    const type = event.type
    const eventSeq = event.sequence ?? 0

    if (type === 'step.completed') {
      const stepId = event.data?.step_id
      if (!stepId) return null

      return events
        .filter(e =>
          e.type === 'step.started' &&
          e.data?.step_id === stepId &&
          (e.sequence ?? 0) < eventSeq
        )
        .sort((a, b) => (b.sequence ?? 0) - (a.sequence ?? 0))[0] ?? null
    } else if (type === 'workflow.completed') {
      return events
        .filter(e =>
          e.type === 'workflow.started' &&
          (e.sequence ?? 0) < eventSeq
        )
        .sort((a, b) => (b.sequence ?? 0) - (a.sequence ?? 0))[0] ?? null
    }

    return null
  }, [events])


  const columns: ColumnDef<Event>[] = useMemo(() => [
    {
      id: 'expander',
      header: () => null,
      cell: ({ row }) => {
        const hasData = Object.keys(row.original.data || {}).length > 0
        if (!hasData) return null

        return (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0"
            onClick={() => row.toggleExpanded()}
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </Button>
        )
      },
      enableSorting: false,
      enableHiding: false,
      meta: {
        className: 'w-[40px]',
      },
    },
    {
      accessorKey: 'sequence',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="#" />
      ),
      cell: ({ row }) => (
        <span className="font-mono text-sm">{row.getValue('sequence')}</span>
      ),
      meta: {
        className: 'w-[60px]',
      },
    },
    {
      accessorKey: 'type',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Event Type" />
      ),
      cell: ({ row }) => {
        const type = row.getValue('type') as string
        return (
          <Badge variant={getEventBadgeVariant(type)}>
            {formatEventType(type)}
          </Badge>
        )
      },
      filterFn: (row, id, value) => {
        return value.includes(row.getValue(id))
      },
    },
    {
      accessorKey: 'timestamp',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Time" />
      ),
      cell: ({ row }) => {
        const timestamp = row.getValue('timestamp') as string
        return (
          <span className="text-sm text-muted-foreground">
            {formatDistanceToNow(new Date(timestamp), { addSuffix: true })}
          </span>
        )
      },
    },
    {
      id: 'step_name',
      accessorFn: (row) => row.data?.step_name ?? '',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Step" />
      ),
      cell: ({ row }) => {
        const stepName = row.original.data?.step_name as string | undefined
        if (!stepName) return <span className="text-muted-foreground">-</span>
        return <span className="font-mono text-sm">{stepName}</span>
      },
      filterFn: (row, _id, value) => {
        const stepName = row.original.data?.step_name
        if (!stepName) return value.length === 0
        return value.includes(stepName)
      },
    },
    {
      id: 'duration',
      header: 'Duration',
      cell: ({ row }) => {
        const duration = getDuration(row.original)
        if (duration === null) {
          return <span className="text-muted-foreground">-</span>
        }
        return (
          <span className="font-mono text-sm">
            {formatDuration(duration)}
          </span>
        )
      },
      enableSorting: false,
    },
  ], [getDuration])

  const table = useReactTable({
    data: events,
    columns,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      expanded,
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: handleColumnFiltersChange,
    onColumnVisibilityChange: setColumnVisibility,
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: (row) => Object.keys(row.original.data || {}).length > 0,
  })

  // Build filters array
  const filters = useMemo(() => {
    const result = []
    if (uniqueEventTypes.length > 0) {
      result.push({ columnId: 'type', title: 'Event Type', options: uniqueEventTypes })
    }
    if (uniqueStepNames.length > 0) {
      result.push({ columnId: 'step_name', title: 'Step', options: uniqueStepNames })
    }
    return result
  }, [uniqueEventTypes, uniqueStepNames])

  return (
    <div className="flex flex-1 flex-col gap-4">
      <DataTableToolbar
        table={table}
        searchKey="type"
        searchPlaceholder="Search events..."
        filters={filters}
      />

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
                <>
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && 'selected'}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as { className?: string } | undefined
                      return (
                        <TableCell key={cell.id} className={`py-2 ${meta?.className || ''}`}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                  {row.getIsExpanded() && (
                    <TableRow key={`${row.id}-expanded`}>
                      <TableCell colSpan={columns.length} className="bg-muted/30 p-4">
                        <div className="flex justify-between items-start mb-3">
                          <span className="text-xs text-muted-foreground font-mono">
                            {row.original.event_id}
                          </span>
                          <div className="text-xs text-right">
                            <span className="text-muted-foreground">Event Timestamp: </span>
                            <span className="font-mono">
                              {format(new Date(row.original.timestamp), 'MMM d, yyyy HH:mm:ss.SSS')}
                            </span>
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          {/* Left side: Data */}
                          <div>
                            <h4 className="text-xs font-medium text-muted-foreground mb-2">Data</h4>
                            <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-48 overflow-y-auto">
                              {row.original.data && Object.keys(row.original.data).length > 0
                                ? JSON.stringify(row.original.data, null, 2)
                                : '-'}
                            </pre>
                          </div>
                          {/* Right side: Duration & Start Time */}
                          <div>
                            <h4 className="text-xs font-medium text-muted-foreground mb-2">Timing</h4>
                            <div className="bg-muted p-3 rounded space-y-2">
                              {(() => {
                                const duration = getDuration(row.original)
                                const startEvent = getStartEvent(row.original)
                                const startTime = startEvent?.timestamp

                                if (!duration && !startTime) {
                                  return <span className="text-xs text-muted-foreground">-</span>
                                }

                                const eventType = row.original.type
                                const isCompleted = eventType === 'step.completed' || eventType === 'workflow.completed'

                                return (
                                  <>
                                    {startTime && (
                                      <div className="flex justify-between text-xs">
                                        <span className="text-muted-foreground">Started:</span>
                                        <span className="font-mono">{format(new Date(startTime), 'MMM d, yyyy HH:mm:ss.SSS')}</span>
                                      </div>
                                    )}
                                    {isCompleted && (
                                      <div className="flex justify-between text-xs">
                                        <span className="text-muted-foreground">Ended:</span>
                                        <span className="font-mono">{format(new Date(row.original.timestamp), 'MMM d, yyyy HH:mm:ss.SSS')}</span>
                                      </div>
                                    )}
                                    {duration !== null && (
                                      <div className="flex justify-between text-xs">
                                        <span className="text-muted-foreground">Duration:</span>
                                        <span className="font-mono">{formatDuration(duration)}</span>
                                      </div>
                                    )}
                                  </>
                                )
                              })()}
                            </div>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center"
                >
                  No events recorded.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
