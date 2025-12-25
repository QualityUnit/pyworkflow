/**
 * Runs list page.
 */

import { useState, useCallback } from 'react'
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

interface RunsListProps {
  workflowName?: string
}

export function RunsList({ workflowName }: RunsListProps) {
  const navigate = useNavigate()
  const [currentPage, setCurrentPage] = useState(0)
  const [userAutoRefresh, setUserAutoRefresh] = useState(true)

  // Auto-refresh is enabled only on page 1 and when user hasn't disabled it
  const autoRefreshEnabled = currentPage === 0 && userAutoRefresh

  // Fetch all runs - filtering is done client-side in the table
  const { data, isLoading, isFetching, error, refetch } = useRuns({
    params: {
      workflow_name: workflowName,
      limit: 1000,
    },
    autoRefresh: autoRefreshEnabled,
  })

  const clearWorkflowFilter = () => {
    navigate({ to: '/runs', search: {} })
  }

  const handlePageChange = useCallback((pageIndex: number) => {
    setCurrentPage(pageIndex)
  }, [])

  const handleAutoRefreshChange = useCallback((enabled: boolean) => {
    setUserAutoRefresh(enabled)
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
              {workflowName ? `Runs: ${workflowName}` : 'Workflow Runs'}
            </h2>
            <p className="text-muted-foreground">
              {data ? `${data.count} run${data.count !== 1 ? 's' : ''}` : 'Loading...'}
            </p>
          </div>
          {workflowName && (
            <Badge variant="secondary" className="flex items-center gap-1">
              Filtered by workflow: {workflowName}
              <button
                onClick={clearWorkflowFilter}
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
              <RunsTable runs={data.items} onPageChange={handlePageChange} />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
