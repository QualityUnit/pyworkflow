/**
 * Main workflow timeline component.
 * Combines the chart, controls, legend, and details panel.
 */

import { useState, useMemo, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
} from '@/components/ui/collapsible'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { Event } from '@/api/types'
import type { TimelineEvent, ViewMode } from './timeline-types'
import {
  processEventsForTimeline,
  findWorkflowStartTime,
  calculateTotalDuration,
  formatDuration,
  formatEventType,
  pairEvents,
} from './timeline-utils'
import { WorkflowTimelineChart } from './workflow-timeline-chart'
import { TimelineDetailsPanel } from './timeline-details-panel'
import { TimelineControls, TimelineLegend } from './timeline-controls'

interface WorkflowTimelineProps {
  events: Event[]
  isActive?: boolean
}

export function WorkflowTimeline({ events, isActive = false }: WorkflowTimelineProps) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [isPanelOpen, setIsPanelOpen] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('compact')
  const [hoveredEvent, setHoveredEvent] = useState<TimelineEvent | null>(null)

  // Process events for timeline display
  const workflowStartTime = useMemo(
    () => findWorkflowStartTime(events),
    [events]
  )

  const timelineEvents = useMemo(
    () => processEventsForTimeline(events, workflowStartTime),
    [events, workflowStartTime]
  )

  const totalDurationMs = useMemo(
    () => calculateTotalDuration(timelineEvents),
    [timelineEvents]
  )

  // Get event pairs for finding paired events
  const eventPairs = useMemo(() => pairEvents(timelineEvents), [timelineEvents])

  // Find selected event
  const selectedEvent = useMemo(
    () => timelineEvents.find((e) => e.event_id === selectedEventId) ?? null,
    [timelineEvents, selectedEventId]
  )

  // Find paired event for selected event
  const pairedEvent = useMemo(() => {
    if (!selectedEvent) return null

    // Find the pair containing this event
    const pair = eventPairs.find(
      (p) =>
        p.startEvent.event_id === selectedEventId ||
        p.endEvent?.event_id === selectedEventId
    )

    if (!pair) return null

    // Return the other event in the pair
    if (pair.startEvent.event_id === selectedEventId) {
      return pair.endEvent ?? null
    }
    return pair.startEvent
  }, [selectedEvent, selectedEventId, eventPairs])

  // Handle event click
  const handleEventClick = useCallback((eventId: string) => {
    setSelectedEventId((prev) => {
      if (prev === eventId) {
        // Clicking same event toggles panel
        setIsPanelOpen((open) => !open)
        return prev
      }
      // New event opens panel
      setIsPanelOpen(true)
      return eventId
    })
  }, [])

  // Handle event hover
  const handleEventHover = useCallback((event: TimelineEvent | null) => {
    setHoveredEvent(event)
  }, [])

  // Handle panel close
  const handlePanelClose = useCallback(() => {
    setIsPanelOpen(false)
  }, [])

  // Don't render if no events
  if (events.length === 0) {
    return null
  }

  return (
    <Card className="mb-4">
      <CardHeader className="pb-2">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Event Timeline</CardTitle>
            {isActive && (
              <span className="flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              {events.length} events &middot; {formatDuration(totalDurationMs)}
            </span>
          </div>
          <TimelineControls
            viewMode={viewMode}
            onViewModeChange={setViewMode}
          />
        </div>
        <TimelineLegend />
      </CardHeader>

      <CardContent className="pt-0 pb-0">
        <TooltipProvider delayDuration={100}>
          <Tooltip open={!!hoveredEvent}>
            <TooltipTrigger asChild>
              <div>
                <WorkflowTimelineChart
                  events={timelineEvents}
                  rawEvents={events}
                  totalDurationMs={totalDurationMs}
                  selectedEventId={selectedEventId}
                  onEventClick={handleEventClick}
                  onEventHover={handleEventHover}
                  viewMode={viewMode}
                />
              </div>
            </TooltipTrigger>
            {hoveredEvent && (
              <TooltipContent
                side="top"
                className="max-w-xs"
                sideOffset={5}
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: hoveredEvent.color }}
                  />
                  <span className="font-medium">
                    {formatEventType(hoveredEvent.type)}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  +{formatDuration(hoveredEvent.relativeTimeMs)}
                  {hoveredEvent.data?.step_name ? (
                    <span> &middot; {String(hoveredEvent.data.step_name)}</span>
                  ) : null}
                </div>
              </TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>

        <div className="text-xs text-muted-foreground text-center py-1 border-t">
          Click events for details &middot; Drag to pan &middot; Scroll to zoom &middot; Double-click to reset
        </div>
      </CardContent>

      <Collapsible open={isPanelOpen} onOpenChange={setIsPanelOpen}>
        <CollapsibleContent>
          <TimelineDetailsPanel
            event={selectedEvent}
            pairedEvent={pairedEvent}
            onClose={handlePanelClose}
          />
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

export { WorkflowTimelineChart } from './workflow-timeline-chart'
export { TimelineDetailsPanel } from './timeline-details-panel'
export { TimelineControls, TimelineLegend } from './timeline-controls'
export type { TimelineEvent, EventCategory, ViewMode, Lane } from './timeline-types'
export { extractLanes } from './timeline-utils'
