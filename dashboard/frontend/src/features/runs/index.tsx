/**
 * Runs list page.
 */

import { useNavigate } from '@tanstack/react-router'
import { RefreshCw, X } from 'lucide-react'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useRuns } from '@/hooks/use-runs'
import { RunsTable } from './components/runs-table'

interface RunsListProps {
  workflowName?: string
}

export function RunsList({ workflowName }: RunsListProps) {
  const navigate = useNavigate()

  // Fetch all runs - filtering is done client-side in the table
  const { data, isLoading, error, refetch } = useRuns({
    workflow_name: workflowName,
    limit: 1000,
  })

  const clearWorkflowFilter = () => {
    navigate({ to: '/runs', search: {} })
  }

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">Workflow Runs</h1>
        <div className="ms-auto flex items-center space-x-4">
          <Button variant="ghost" size="icon" onClick={() => refetch()}>
            <RefreshCw className="h-4 w-4" />
            <span className="sr-only">Refresh</span>
          </Button>
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
              <RunsTable runs={data.items} />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
