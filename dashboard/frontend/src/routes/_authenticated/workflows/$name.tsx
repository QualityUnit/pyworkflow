import { createFileRoute } from '@tanstack/react-router'
import { WorkflowDetail } from '@/features/workflows/workflow-detail'

export const Route = createFileRoute('/_authenticated/workflows/$name')({
  component: () => {
    const { name } = Route.useParams()
    return <WorkflowDetail workflowName={name} />
  },
})
