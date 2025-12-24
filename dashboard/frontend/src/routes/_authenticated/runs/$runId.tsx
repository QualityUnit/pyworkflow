import { createFileRoute } from '@tanstack/react-router'
import { RunDetail } from '@/features/runs/run-detail'

export const Route = createFileRoute('/_authenticated/runs/$runId')({
  component: () => {
    const { runId } = Route.useParams()
    return <RunDetail runId={runId} />
  },
})
