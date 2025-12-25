import { createFileRoute } from '@tanstack/react-router'
import { RunsList } from '@/features/runs'

interface RunsSearchParams {
  workflow_name?: string
}

export const Route = createFileRoute('/_authenticated/runs/')({
  validateSearch: (search: Record<string, unknown>): RunsSearchParams => {
    return {
      workflow_name: typeof search.workflow_name === 'string' ? search.workflow_name : undefined,
    }
  },
  component: () => {
    const { workflow_name } = Route.useSearch()
    return <RunsList workflowName={workflow_name} />
  },
})
