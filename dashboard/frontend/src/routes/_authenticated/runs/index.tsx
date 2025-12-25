import { createFileRoute } from '@tanstack/react-router'
import { RunsList } from '@/features/runs'

interface RunsSearchParams {
  query?: string
}

export const Route = createFileRoute('/_authenticated/runs/')({
  validateSearch: (search: Record<string, unknown>): RunsSearchParams => {
    return {
      query: typeof search.query === 'string' ? search.query : undefined,
    }
  },
  component: () => {
    const { query } = Route.useSearch()
    return <RunsList query={query} />
  },
})
