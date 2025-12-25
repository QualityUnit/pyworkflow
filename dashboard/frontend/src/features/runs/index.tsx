/**
 * Runs list page.
 */

import { useState, useCallback, useMemo } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { RefreshButton } from '@/components/refresh-button'
import { Badge } from '@/components/ui/badge'
import { useRuns, REFRESH_INTERVAL } from '@/hooks/use-runs'
import { RunsTable } from './components/runs-table'

export interface DateRange {
  from: Date | null
  to: Date | null
}

export interface RunsFilters {
  searchQuery: string
  statusFilter: string | null
  workflowFilter: string | null
}

interface RunsListProps {
  query?: string
}

export function RunsList({ query }: RunsListProps) {
  const navigate = useNavigate()
  const [currentPage, setCurrentPage] = useState(0)
  const [userAutoRefresh, setUserAutoRefresh] = useState(true)
  const [dateRange, setDateRange] = useState<DateRange>({ from: null, to: null })
  const [filters, setFilters] = useState<RunsFilters>({
    searchQuery: '',
    statusFilter: null,
    workflowFilter: null,
  })

  // Auto-refresh is enabled only on page 1 and when user hasn't disabled it
  const autoRefreshEnabled = currentPage === 0 && userAutoRefresh

  // Build API params including all filters
  const fromTime = dateRange.from?.getTime() ?? null
  const toTime = dateRange.to?.getTime() ?? null

  const apiParams = useMemo(() => {
    const params: {
      query?: string
      status?: string
      limit: number
      start_time?: string
      end_time?: string
    } = {
      limit: 1000,
    }

    // Use URL query param if provided, otherwise use search filter
    // Also include workflow filter in the query
    const searchParts: string[] = []
    if (query) searchParts.push(query)
    if (filters.searchQuery) searchParts.push(filters.searchQuery)
    if (filters.workflowFilter) searchParts.push(filters.workflowFilter)

    if (searchParts.length > 0) {
      params.query = searchParts.join(' ')
    }

    // Status filter
    if (filters.statusFilter) {
      params.status = filters.statusFilter
    }

    if (dateRange.from) {
      params.start_time = dateRange.from.toISOString()
    }
    if (dateRange.to) {
      params.end_time = dateRange.to.toISOString()
    }

    return params
  }, [query, filters.searchQuery, filters.statusFilter, filters.workflowFilter, dateRange.from, dateRange.to, fromTime, toTime])

  // Fetch runs with server-side filtering
  const { data, isLoading, isFetching, error, refetch } = useRuns({
    params: apiParams,
    autoRefresh: autoRefreshEnabled,
  })

  const clearQueryFilter = () => {
    navigate({ to: '/runs', search: {} })
  }

  const handlePageChange = useCallback((pageIndex: number) => {
    setCurrentPage(pageIndex)
  }, [])

  const handleAutoRefreshChange = useCallback((enabled: boolean) => {
    setUserAutoRefresh(enabled)
  }, [])

  const handleFiltersChange = useCallback((newFilters: RunsFilters) => {
    setFilters(newFilters)
    // Reset to first page when filters change
    setCurrentPage(0)
  }, [])

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">Workflow Runs</h1>
        <div className="ms-auto flex items-center space-x-4">
          <RefreshButton
            onRefresh={() => refetch()}
            intervalMs={REFRESH_INTERVAL}
            isFetching={isFetching}
            autoRefreshEnabled={autoRefreshEnabled}
            onAutoRefreshChange={handleAutoRefreshChange}
          />
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main fixed>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              {query ? `Search: ${query}` : 'Workflow Runs'}
            </h2>
            <p className="text-muted-foreground">
              {data ? `${data.count} run${data.count !== 1 ? 's' : ''}` : 'Loading...'}
            </p>
          </div>
          {query && (
            <Badge variant="secondary" className="flex items-center gap-1">
              Search: {query}
              <button
                onClick={clearQueryFilter}
                className="ml-1 hover:bg-muted rounded-full p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
        </div>

        {isLoading && (
          <div className="text-center py-8 text-muted-foreground">
            Loading runs...
          </div>
        )}

        {error && (
          <div className="text-center py-8 text-destructive">
            Error loading runs: {error.message}
          </div>
        )}

        {data && (
          <div className="-mx-4 flex-1 overflow-auto px-4 py-1 lg:flex-row lg:space-x-12 lg:space-y-0">
            <div className="@container/content h-full">
              <RunsTable
                runs={data.items}
                onPageChange={handlePageChange}
                dateRange={dateRange}
                onDateRangeChange={setDateRange}
                filters={filters}
                onFiltersChange={handleFiltersChange}
              />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
