import { createFileRoute } from '@tanstack/react-router'
import { WorkflowsList } from '@/features/workflows'

export const Route = createFileRoute('/_authenticated/workflows/')({
  component: WorkflowsList,
})
