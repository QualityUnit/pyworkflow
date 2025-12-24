import { createFileRoute } from '@tanstack/react-router'
import { RunsList } from '@/features/runs'

export const Route = createFileRoute('/_authenticated/runs/')({
  component: RunsList,
})
