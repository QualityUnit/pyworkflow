/**
 * Run detail page.
 */

import { Link } from '@tanstack/react-router'
import { formatDistanceToNow } from 'date-fns'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRun, useRunEvents } from '@/hooks/use-runs'
import { StatusBadge } from './components/status-badge'
import { EventsTable } from './components/events-table'
import { ArrowLeft, ExternalLink, Copy, Check } from 'lucide-react'
import { useState, useCallback, useMemo } from 'react'
import { toast } from 'sonner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Filter } from 'lucide-react'

interface RunDetailProps {
  runId: string
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString()
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '-'
  return formatDistanceToNow(new Date(dateStr), { addSuffix: true })
}

// Step summary derived from events
interface StepSummary {
  stepName: string
  eventCounts: Record<string, number>
  totalEvents: number
}

export function RunDetail({ runId }: RunDetailProps) {
  const { data: run, isLoading: runLoading, error: runError } = useRun(runId)
  const { data: events } = useRunEvents(runId)
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('events')
  const [stepFilter, setStepFilter] = useState<string[]>([])
  const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([])

  // Derive step summaries from events
  const stepSummaries = useMemo<StepSummary[]>(() => {
    if (!events?.items) return []

    const stepMap = new Map<string, Record<string, number>>()

    events.items.forEach((event) => {
      const stepName = event.data?.step_name as string | undefined
      if (!stepName) return

      if (!stepMap.has(stepName)) {
        stepMap.set(stepName, {})
      }

      const counts = stepMap.get(stepName)!
      counts[event.type] = (counts[event.type] || 0) + 1
    })

    return Array.from(stepMap.entries())
      .map(([stepName, eventCounts]) => ({
        stepName,
        eventCounts,
        totalEvents: Object.values(eventCounts).reduce((a, b) => a + b, 0),
      }))
      .sort((a, b) => b.totalEvents - a.totalEvents)
  }, [events])

  // Handle filtering from steps tab
  const handleFilterByStep = useCallback((stepName: string) => {
    setStepFilter([stepName])
    setEventTypeFilter([])
    setActiveTab('events')
  }, [])

  const handleCopyRunId = useCallback(() => {
    navigator.clipboard.writeText(runId)
    setCopied(true)
    toast.success('Run ID copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }, [runId])

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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 mb-6">
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
              <Link
                to="/workflows/$name"
                params={{ name: run.workflow_name }}
                className="text-primary hover:underline flex items-center gap-1"
              >
                {run.workflow_name}
                <ExternalLink className="h-3 w-3" />
              </Link>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Run ID</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs truncate">{run.run_id}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={handleCopyRunId}
                >
                  {copied ? (
                    <Check className="h-3 w-3 text-green-500" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Started</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm" title={formatDate(run.started_at)}>
                {formatRelativeTime(run.started_at)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Completed</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm" title={formatDate(run.completed_at)}>
                {run.completed_at ? formatRelativeTime(run.completed_at) : '-'}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Events</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">{events?.count || 0}</div>
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

        {/* Inputs/Outputs Section */}
        {(run.input_args !== null || run.input_kwargs !== null || run.result !== null) && (
          <div className="grid gap-4 md:grid-cols-2 mb-6">
            {(run.input_args !== null || run.input_kwargs !== null) && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium">Inputs</CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-[200px]">
                    {JSON.stringify({ args: run.input_args, kwargs: run.input_kwargs }, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            )}
            {run.result !== null && run.result !== undefined && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium">Output</CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-[200px]">
                    {JSON.stringify(run.result, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Tabs for events, steps */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="events">
              Events ({events?.count || 0})
            </TabsTrigger>
            <TabsTrigger value="steps">
              Steps ({stepSummaries.length})
            </TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
          </TabsList>

          <TabsContent value="events" className="mt-4">
            {events && (
              <EventsTable
                events={events.items}
                initialStepFilter={stepFilter}
                initialEventTypeFilter={eventTypeFilter}
                onFiltersChange={(steps, types) => {
                  setStepFilter(steps)
                  setEventTypeFilter(types)
                }}
              />
            )}
          </TabsContent>

          <TabsContent value="steps" className="mt-4">
            {stepSummaries.length > 0 ? (
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Step Name</TableHead>
                      <TableHead className="text-right">Events</TableHead>
                      <TableHead className="text-right">Breakdown</TableHead>
                      <TableHead className="w-[80px]">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stepSummaries.map((step) => (
                      <TableRow key={step.stepName}>
                        <TableCell className="font-mono text-sm">
                          {step.stepName}
                        </TableCell>
                        <TableCell className="text-right">
                          {step.totalEvents}
                        </TableCell>
                        <TableCell className="text-right text-xs text-muted-foreground">
                          {Object.entries(step.eventCounts)
                            .map(([type, count]) => `${type.split('.')[1]}: ${count}`)
                            .join(', ')}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleFilterByStep(step.stepName)}
                            title="Filter events by this step"
                          >
                            <Filter className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No steps recorded.
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
