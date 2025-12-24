/**
 * Run detail page.
 */

import { Link } from '@tanstack/react-router'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRun, useRunEvents, useRunSteps, useRunHooks } from '@/hooks/use-runs'
import { StatusBadge } from './components/status-badge'
import { EventTimeline } from './components/event-timeline'
import { ArrowLeft } from 'lucide-react'

interface RunDetailProps {
  runId: string
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '-'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

export function RunDetail({ runId }: RunDetailProps) {
  const { data: run, isLoading: runLoading, error: runError } = useRun(runId)
  const { data: events } = useRunEvents(runId)
  const { data: steps } = useRunSteps(runId)
  const { data: hooks } = useRunHooks(runId)

  if (runLoading) {
    return (
      <>
        <Header>
          <h1 className="text-lg font-semibold">Run Details</h1>
        </Header>
        <Main>
          <div className="text-center py-8 text-muted-foreground">
            Loading run details...
          </div>
        </Main>
      </>
    )
  }

  if (runError || !run) {
    return (
      <>
        <Header>
          <h1 className="text-lg font-semibold">Run Details</h1>
        </Header>
        <Main>
          <div className="text-center py-8 text-destructive">
            {runError ? `Error: ${runError.message}` : 'Run not found'}
          </div>
        </Main>
      </>
    )
  }

  return (
    <>
      <Header>
        <div className="flex items-center gap-4">
          <Link to="/runs">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <h1 className="text-lg font-semibold">Run Details</h1>
        </div>
        <div className="ms-auto flex items-center space-x-4">
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        {/* Run summary */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Status</CardTitle>
            </CardHeader>
            <CardContent>
              <StatusBadge status={run.status} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Workflow</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">{run.workflow_name}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Duration</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">
                {formatDuration(run.duration_seconds)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Created</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                {formatDate(run.created_at)}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Error display */}
        {run.error && (
          <Card className="mb-6 border-destructive">
            <CardHeader>
              <CardTitle className="text-destructive">Error</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-sm bg-muted p-4 rounded overflow-x-auto whitespace-pre-wrap">
                {run.error}
              </pre>
            </CardContent>
          </Card>
        )}

        {/* Tabs for events, steps, hooks */}
        <Tabs defaultValue="events">
          <TabsList>
            <TabsTrigger value="events">
              Events ({events?.count || 0})
            </TabsTrigger>
            <TabsTrigger value="steps">
              Steps ({steps?.count || 0})
            </TabsTrigger>
            <TabsTrigger value="hooks">
              Hooks ({hooks?.count || 0})
            </TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
          </TabsList>

          <TabsContent value="events" className="mt-4">
            {events && <EventTimeline events={events.items} />}
          </TabsContent>

          <TabsContent value="steps" className="mt-4">
            {steps && steps.items.length > 0 ? (
              <div className="space-y-2">
                {steps.items.map((step) => (
                  <Card key={step.step_id}>
                    <CardHeader className="py-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium">
                          {step.step_name}
                        </CardTitle>
                        <StatusBadge status={step.status} />
                      </div>
                    </CardHeader>
                    <CardContent className="py-2">
                      <div className="text-sm text-muted-foreground">
                        Attempt {step.attempt} of {step.max_retries} | Duration:{' '}
                        {formatDuration(step.duration_seconds)}
                      </div>
                      {step.error && (
                        <pre className="mt-2 text-xs bg-destructive/10 text-destructive p-2 rounded">
                          {step.error}
                        </pre>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No steps recorded.
              </div>
            )}
          </TabsContent>

          <TabsContent value="hooks" className="mt-4">
            {hooks && hooks.items.length > 0 ? (
              <div className="space-y-2">
                {hooks.items.map((hook) => (
                  <Card key={hook.hook_id}>
                    <CardHeader className="py-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium">
                          {hook.name || hook.hook_id}
                        </CardTitle>
                        <StatusBadge status={hook.status} />
                      </div>
                    </CardHeader>
                    <CardContent className="py-2 text-sm text-muted-foreground">
                      Created: {formatDate(hook.created_at)}
                      {hook.expires_at && ` | Expires: ${formatDate(hook.expires_at)}`}
                      {hook.has_payload && ' | Has payload'}
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No hooks recorded.
              </div>
            )}
          </TabsContent>

          <TabsContent value="details" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Run Details</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Run ID</dt>
                    <dd className="font-mono text-sm">{run.run_id}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Workflow</dt>
                    <dd>{run.workflow_name}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Started</dt>
                    <dd>{formatDate(run.started_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Completed</dt>
                    <dd>{formatDate(run.completed_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Recovery Attempts</dt>
                    <dd>{run.recovery_attempts} / {run.max_recovery_attempts}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Max Duration</dt>
                    <dd>{run.max_duration || '-'}</dd>
                  </div>
                </dl>

                {run.result !== null && run.result !== undefined && (
                  <div className="mt-6">
                    <h4 className="text-sm font-medium text-muted-foreground mb-2">Result</h4>
                    <pre className="text-sm bg-muted p-4 rounded overflow-x-auto">
                      {JSON.stringify(run.result, null, 2)}
                    </pre>
                  </div>
                )}

                {(run.input_args !== null || run.input_kwargs !== null) && (
                  <div className="mt-6">
                    <h4 className="text-sm font-medium text-muted-foreground mb-2">Input</h4>
                    <pre className="text-sm bg-muted p-4 rounded overflow-x-auto">
                      {JSON.stringify({ args: run.input_args, kwargs: run.input_kwargs }, null, 2)}
                    </pre>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}
