/**
 * Run detail page.
 */

import { Link } from '@tanstack/react-router'
import { formatDistanceToNow } from 'date-fns'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { GithubStarButton } from '@/components/github-star-button'
import { ThemeSwitch } from '@/components/theme-switch'
import { RefreshButton } from '@/components/refresh-button'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { useRun, useRunEvents, REFRESH_INTERVAL } from '@/hooks/use-runs'
import { StatusBadge } from './components/status-badge'
import { EventsTable } from './components/events-table'
import { ExternalLink, Copy, Check, ChevronDown, Filter } from 'lucide-react'
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
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)
  const { data: run, isLoading: runLoading, isFetching: runFetching, error: runError, refetch: refetchRun } = useRun(runId, { autoRefresh: autoRefreshEnabled })
  const { data: events, isFetching: eventsFetching, refetch: refetchEvents } = useRunEvents(runId, { autoRefresh: autoRefreshEnabled })
  const isFetching = runFetching || eventsFetching
  const refetch = useCallback(() => {
    refetchRun()
    refetchEvents()
  }, [refetchRun, refetchEvents])
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
          <Breadcrumb>
            <BreadcrumbList className="text-lg">
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/runs">Runs</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage className="font-semibold">Loading...</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="ms-auto flex items-center space-x-4">
            <RefreshButton
              onRefresh={refetch}
              intervalMs={REFRESH_INTERVAL}
              isFetching={isFetching}
              autoRefreshEnabled={autoRefreshEnabled}
              onAutoRefreshChange={setAutoRefreshEnabled}
            />
            <ThemeSwitch />
            <GithubStarButton />
          </div>
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
          <Breadcrumb>
            <BreadcrumbList className="text-lg">
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/runs">Runs</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage className="font-semibold">Error</BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="ms-auto flex items-center space-x-4">
            <RefreshButton
              onRefresh={refetch}
              intervalMs={REFRESH_INTERVAL}
              isFetching={isFetching}
              autoRefreshEnabled={autoRefreshEnabled}
              onAutoRefreshChange={setAutoRefreshEnabled}
            />
            <ThemeSwitch />
            <GithubStarButton />
          </div>
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
        <Breadcrumb>
          <BreadcrumbList className="text-lg">
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/runs">Runs</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage className="font-semibold">{run.run_id}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div className="ms-auto flex items-center space-x-4">
          <RefreshButton
            onRefresh={refetch}
            intervalMs={REFRESH_INTERVAL}
            isFetching={isFetching}
            autoRefreshEnabled={autoRefreshEnabled}
            onAutoRefreshChange={setAutoRefreshEnabled}
          />
          <ThemeSwitch />
          <GithubStarButton />
        </div>
      </Header>

      <Main>
        {/* Title row with run_id and status */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold font-mono">{run.run_id}</h2>
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
          <StatusBadge status={run.status} />
        </div>

        {/* Run details collapsible */}
        <Collapsible className="mb-6">
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-2 p-0 h-auto hover:bg-transparent">
              <ChevronDown className="h-4 w-4 transition-transform duration-200 [[data-state=closed]_&]:-rotate-90" />
              <span className="text-sm text-muted-foreground">Run Details</span>
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 bg-muted/30 rounded-lg">
              <div>
                <div className="text-sm text-muted-foreground">Workflow</div>
                <Link
                  to="/workflows/$name"
                  params={{ name: run.workflow_name }}
                  className="text-primary hover:underline flex items-center gap-1"
                >
                  {run.workflow_name}
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">Started</div>
                <div className="text-sm" title={formatDate(run.started_at)}>
                  {formatRelativeTime(run.started_at)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">Completed</div>
                <div className="text-sm" title={formatDate(run.completed_at)}>
                  {run.completed_at ? formatRelativeTime(run.completed_at) : '-'}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground">Events</div>
                <div className="text-sm font-semibold">{events?.count || 0}</div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

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
