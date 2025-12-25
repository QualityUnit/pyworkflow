/**
 * Workflow detail page.
 */

import { Link } from '@tanstack/react-router'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { useWorkflow } from '@/hooks/use-workflows'
import { useRuns } from '@/hooks/use-runs'
import { RunsTable } from '@/features/runs/components/runs-table'
import { ExternalLink } from 'lucide-react'

interface WorkflowDetailProps {
  workflowName: string
}

export function WorkflowDetail({ workflowName }: WorkflowDetailProps) {
  const { data: workflow, isLoading: workflowLoading, error: workflowError } = useWorkflow(workflowName)
  const { data: runsData, isLoading: runsLoading } = useRuns({ params: { query: workflowName, limit: 10 } })

  if (workflowLoading) {
    return (
      <>
        <Header>
          <h1 className="text-lg font-semibold">Workflow Details</h1>
        </Header>
        <Main>
          <div className="text-center py-8 text-muted-foreground">
            Loading workflow details...
          </div>
        </Main>
      </>
    )
  }

  if (workflowError || !workflow) {
    return (
      <>
        <Header>
          <h1 className="text-lg font-semibold">Workflow Details</h1>
        </Header>
        <Main>
          <div className="text-center py-8 text-destructive">
            {workflowError ? `Error: ${workflowError.message}` : 'Workflow not found'}
          </div>
        </Main>
      </>
    )
  }

  return (
    <>
      <Header>
        <Breadcrumb>
          <BreadcrumbList className="text-lg">
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/workflows">My Workflows</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage className="font-semibold">{workflowName}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        {/* Workflow Info */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Max Duration</CardTitle>
            </CardHeader>
            <CardContent>
              {workflow.max_duration ? (
                <Badge variant="outline">{workflow.max_duration}</Badge>
              ) : (
                <span className="text-muted-foreground">No limit</span>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Runs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">
                {runsLoading ? '...' : runsData?.count || 0}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Tags */}
        {workflow.tags.length > 0 && (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>Tags</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                {workflow.tags.map((tag) => (
                  <Badge key={tag} variant="outline">
                    {tag}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Recent Runs */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Recent Runs</CardTitle>
            <Link
              to="/runs"
              search={{ query: workflowName }}
              className="text-sm text-primary hover:underline flex items-center gap-1"
            >
              View all runs
              <ExternalLink className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {runsLoading ? (
              <div className="text-center py-4 text-muted-foreground">
                Loading runs...
              </div>
            ) : runsData && runsData.items.length > 0 ? (
              <RunsTable runs={runsData.items} />
            ) : (
              <div className="text-center py-4 text-muted-foreground">
                No runs yet
              </div>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
