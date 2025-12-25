import { Link } from '@tanstack/react-router'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { useRuns } from '@/hooks/use-runs'
import { useWorkflows } from '@/hooks/use-workflows'
import { useHealth } from '@/hooks/use-health'
import { StatusBadge } from '@/features/runs/components/status-badge'
import { Play, CheckCircle, XCircle, Clock, Activity } from 'lucide-react'

export function Dashboard() {
  const { data: runsData } = useRuns({ params: { limit: 10 } })
  const { data: workflowsData } = useWorkflows()
  const { data: health } = useHealth()

  // Calculate stats from recent runs
  const runs = runsData?.items || []
  const runningCount = runs.filter((r) => r.status === 'running').length
  const completedCount = runs.filter((r) => r.status === 'completed').length
  const failedCount = runs.filter((r) => r.status === 'failed').length
  const suspendedCount = runs.filter((r) => r.status === 'suspended').length

  return (
    <>
      <Header>
        <h1 className="text-lg font-semibold">Dashboard</h1>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        <div className="mb-6">
          <h2 className="text-2xl font-bold tracking-tight">Overview</h2>
          <p className="text-muted-foreground">
            Monitor your workflow executions and system health.
          </p>
        </div>

        {/* Stats cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Running</CardTitle>
              <Play className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{runningCount}</div>
              <p className="text-xs text-muted-foreground">Active workflows</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Completed</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{completedCount}</div>
              <p className="text-xs text-muted-foreground">Recent successes</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Failed</CardTitle>
              <XCircle className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{failedCount}</div>
              <p className="text-xs text-muted-foreground">Recent failures</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Suspended</CardTitle>
              <Clock className="h-4 w-4 text-yellow-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{suspendedCount}</div>
              <p className="text-xs text-muted-foreground">Waiting for events</p>
            </CardContent>
          </Card>
        </div>

        {/* Main content grid */}
        <div className="grid gap-4 lg:grid-cols-7">
          {/* Recent runs */}
          <Card className="lg:col-span-4">
            <CardHeader>
              <CardTitle>Recent Runs</CardTitle>
              <CardDescription>
                Latest workflow executions
              </CardDescription>
            </CardHeader>
            <CardContent>
              {runs.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">
                  No workflow runs yet.
                </p>
              ) : (
                <div className="space-y-4">
                  {runs.slice(0, 5).map((run) => (
                    <div key={run.run_id} className="flex items-center gap-4">
                      <Activity className="h-4 w-4 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <Link
                          to="/runs/$runId"
                          params={{ runId: run.run_id }}
                          className="text-sm font-medium hover:underline"
                        >
                          {run.workflow_name}
                        </Link>
                        <p className="text-xs text-muted-foreground font-mono">
                          {run.run_id.slice(0, 16)}...
                        </p>
                      </div>
                      <StatusBadge status={run.status} />
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 pt-4 border-t">
                <Link
                  to="/runs"
                  className="text-sm text-primary hover:underline"
                >
                  View all runs →
                </Link>
              </div>
            </CardContent>
          </Card>

          {/* System status */}
          <Card className="lg:col-span-3">
            <CardHeader>
              <CardTitle>System Status</CardTitle>
              <CardDescription>
                Health and configuration
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm">API Status</span>
                <StatusBadge status={health?.status === 'healthy' ? 'completed' : 'failed'} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Storage Backend</span>
                <StatusBadge status={health?.storage_healthy ? 'completed' : 'failed'} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Registered Workflows</span>
                <span className="text-sm font-medium">{workflowsData?.count || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Total Runs</span>
                <span className="text-sm font-medium">{runsData?.count || 0}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}
