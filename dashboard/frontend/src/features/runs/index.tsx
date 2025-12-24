/**
 * Runs list page.
 */

import { useState } from 'react'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useRuns } from '@/hooks/use-runs'
import { RunsTable } from './components/runs-table'

const statusOptions = [
  { value: 'all', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'interrupted', label: 'Interrupted' },
  { value: 'cancelled', label: 'Cancelled' },
]

export function RunsList() {
  const [status, setStatus] = useState<string>('all')
  const [limit] = useState(50)

  const { data, isLoading, error, refetch } = useRuns({
    status: status === 'all' ? undefined : status,
    limit,
  })

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">Workflow Runs</h1>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                {statusOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => refetch()}>
            Refresh
          </Button>
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

        {data && <RunsTable runs={data.items} />}

        {data && (
          <div className="mt-4 text-sm text-muted-foreground">
            Showing {data.items.length} of {data.count} runs
          </div>
        )}
      </Main>
    </>
  )
}
