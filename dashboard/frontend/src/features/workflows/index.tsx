/**
 * Workflows list page.
 */

import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { useWorkflows } from '@/hooks/use-workflows'
import { WorkflowsTable } from './components/workflows-table'

export function WorkflowsList() {
  const { data, isLoading, error } = useWorkflows()

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">My Workflows</h1>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main fixed>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Registered Workflows</h2>
            <p className="text-muted-foreground">
              {data ? `${data.count} workflow${data.count !== 1 ? 's' : ''} registered` : 'Loading...'}
            </p>
          </div>
        </div>

        {isLoading && (
          <div className="text-center py-8 text-muted-foreground">
            Loading workflows...
          </div>
        )}

        {error && (
          <div className="text-center py-8 text-destructive">
            Error loading workflows: {error.message}
          </div>
        )}

        {data && (
          <div className="-mx-4 flex-1 overflow-auto px-4 py-1 lg:flex-row lg:space-x-12 lg:space-y-0">
            <div className="@container/content h-full">
              <WorkflowsTable workflows={data.items} />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
