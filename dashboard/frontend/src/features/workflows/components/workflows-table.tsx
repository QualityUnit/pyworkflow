/**
 * Workflows table component with TanStack React Table.
 */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  type ColumnDef,
  type ColumnFiltersState,
  type FilterFn,
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
import { MoreHorizontal, Play, List } from 'lucide-react'
import { NewRunModal } from './new-run-modal'
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
import type { Workflow } from '@/api/types'

interface WorkflowsTableProps {
  workflows: Workflow[]
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength).trim() + '...'
}

// Custom filter function for tags array
const tagsFilterFn: FilterFn<Workflow> = (row, columnId, filterValue) => {
  const tags = row.getValue(columnId) as string[]
  if (!filterValue || filterValue.length === 0) return true
  return filterValue.some((v: string) => tags.includes(v))
}

export function WorkflowsTable({ workflows }: WorkflowsTableProps) {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})

  // Modal state
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null)
  const [isNewRunModalOpen, setIsNewRunModalOpen] = useState(false)

  const handleViewRuns = useCallback(
    (workflowName: string) => {
      navigate({ to: '/runs', search: { workflow_name: workflowName } })
    },
    [navigate]
  )

  const handleNewRun = useCallback(
    (workflow: Workflow) => {
      setSelectedWorkflow(workflow)
      setIsNewRunModalOpen(true)
    },
    []
  )

  const handleRowClick = useCallback(
    (workflowName: string) => {
      navigate({ to: '/workflows/$name', params: { name: workflowName } })
    },
    [navigate]
  )

  const columns: ColumnDef<Workflow>[] = [
    {
      accessorKey: 'name',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Name" />
      ),
      cell: ({ row }) => (
        <div className="font-medium">{row.getValue('name')}</div>
      ),
      enableHiding: false,
      meta: {
        className: 'pl-4',
      },
    },
    {
      accessorKey: 'description',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Description" />
      ),
      cell: ({ row }) => {
        const description = row.getValue('description') as string | null
        const tags = row.original.tags || []
        return (
          <div className="flex items-center gap-2 min-w-[350px]">
            {tags.map((tag) => (
              <Badge key={tag} variant="outline" className="shrink-0">
                {tag}
              </Badge>
            ))}
            {description ? (
              <span className="text-muted-foreground truncate">
                {truncateText(description, 60)}
              </span>
            ) : (
              <span className="text-muted-foreground italic">No description</span>
            )}
          </div>
        )
      },
      enableSorting: false,
    },
    {
      accessorKey: 'tags',
      header: () => null,
      cell: () => null,
      filterFn: tagsFilterFn,
      enableHiding: true,
    },
    {
      accessorKey: 'max_duration',
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Max Duration" />
      ),
      cell: ({ row }) => {
        const maxDuration = row.getValue('max_duration') as string | null
        return maxDuration ? (
          <Badge variant="outline">{maxDuration}</Badge>
        ) : (
          <span className="text-muted-foreground">Unlimited</span>
        )
      },
    },
    {
      id: 'actions',
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => {
        const workflow = row.original

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
                    handleNewRun(workflow)
                  }}
                >
                  <Play className="mr-2 h-4 w-4" />
                  New Workflow Run
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    handleViewRuns(workflow.name)
                  }}
                >
                  <List className="mr-2 h-4 w-4" />
                  View Runs
                </DropdownMenuItem>
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

  // Extract unique tags for filtering
  const uniqueTags = useMemo(() => {
    const tagSet = new Set<string>()
    workflows.forEach((w) => w.tags?.forEach((t) => tagSet.add(t)))
    return Array.from(tagSet)
      .sort()
      .map((tag) => ({ label: tag, value: tag }))
  }, [workflows])

  const table = useReactTable({
    data: workflows,
    columns,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
      columnVisibility: {
        tags: false, // Hide tags column (only used for filtering)
      },
    },
  })

  return (
    <div className="flex flex-1 flex-col gap-4 h-full">
      <DataTableToolbar
        table={table}
        searchKey="name"
        searchPlaceholder="Search workflows..."
        filters={
          uniqueTags.length > 0
            ? [{ columnId: 'tags', title: 'Tags', options: uniqueTags }]
            : []
        }
      />

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
                  onClick={() => handleRowClick(row.original.name)}
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta as { className?: string } | undefined
                    return (
                      <TableCell key={cell.id} className={`py-4 ${meta?.className || ''}`}>
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
                  No workflows registered. Define workflows using the @workflow decorator.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        </div>
      </div>

      <DataTablePagination table={table} className="mt-auto" />

      <NewRunModal
        workflow={selectedWorkflow}
        open={isNewRunModalOpen}
        onOpenChange={setIsNewRunModalOpen}
      />
    </div>
  )
}
