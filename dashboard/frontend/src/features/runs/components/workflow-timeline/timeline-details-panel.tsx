/**
 * Collapsible details panel for selected timeline event.
 */

import { format } from 'date-fns'
import { Badge } from '@/components/ui/badge'
import {
  IconChevronDown,
  IconPlayerPlay,
  IconPlayerStop,
  IconClock,
  IconHourglass,
  IconRoute,
  IconPlayerTrackNext,
  IconMoon,
  IconWebhook,
  IconGitBranch,
} from '@tabler/icons-react'
import type { TimelineEvent, EventCategory } from './timeline-types'
import { formatDuration, formatEventType } from './timeline-utils'

// Category icon mapping using Tabler Icons
export function getCategoryIcon(category: EventCategory, color: string, size: number = 20) {
  const iconProps = { size, color, stroke: 1.5 }
  switch (category) {
    case 'workflow':
      return <IconRoute {...iconProps} />
    case 'step':
      return <IconPlayerTrackNext {...iconProps} />
    case 'sleep':
      return <IconMoon {...iconProps} />
    case 'hook':
      return <IconWebhook {...iconProps} />
    case 'child_workflow':
      return <IconGitBranch {...iconProps} />
    default:
      return <IconRoute {...iconProps} />
  }
}

interface TimelineDetailsPanelProps {
  event: TimelineEvent | null
  pairedEvent?: TimelineEvent | null
  onClose: () => void
}

// Helper functions to check data availability
function hasInput(event: TimelineEvent): boolean {
  return event.data?.input !== undefined || event.data?.args !== undefined
}

function hasOutput(event: TimelineEvent, pairedEvent?: TimelineEvent | null): boolean {
  return event.data?.result !== undefined || event.data?.output !== undefined ||
    pairedEvent?.data?.result !== undefined || pairedEvent?.data?.output !== undefined
}

function hasInputOutput(event: TimelineEvent, pairedEvent?: TimelineEvent | null): boolean {
  return hasInput(event) || hasOutput(event, pairedEvent)
}

export function TimelineDetailsPanel({
  event,
  pairedEvent,
  onClose,
}: TimelineDetailsPanelProps) {
  if (!event) return null

  // Determine which is start and which is end event
  const isStartEvent = event.type.endsWith('.started') || event.type.endsWith('.created')
  const startEvent = isStartEvent ? event : pairedEvent
  const endEvent = isStartEvent ? pairedEvent : event

  const durationMs = startEvent && endEvent
    ? Math.abs(
        new Date(endEvent.timestamp).getTime() -
          new Date(startEvent.timestamp).getTime()
      )
    : null

  // Get badge variant based on event type
  const getBadgeVariant = (): 'default' | 'secondary' | 'destructive' | 'outline' => {
    const effectiveEvent = endEvent || event
    if (effectiveEvent.type.includes('failed') || effectiveEvent.type.includes('expired')) {
      return 'destructive'
    }
    if (effectiveEvent.type.includes('completed') || effectiveEvent.type.includes('received')) {
      return 'default'
    }
    if (effectiveEvent.type.includes('started') || effectiveEvent.type.includes('created')) {
      return 'secondary'
    }
    return 'outline'
  }

  // Get the display name (step name, hook id, or event type)
  const getDisplayName = () => {
    if (event.data?.step_name) return String(event.data.step_name)
    if (event.data?.hook_id) return String(event.data.hook_id)
    if (event.data?.workflow_name) return String(event.data.workflow_name)
    return event.laneName
  }

  // Get category icon wrapper
  const renderCategoryIcon = () => {
    return (
      <div className="p-2 rounded-lg" style={{ backgroundColor: `${event.laneColor}30` }}>
        {getCategoryIcon(event.category, event.laneColor, 20)}
      </div>
    )
  }

  // Get status text
  const getStatusText = () => {
    if (endEvent?.type.includes('failed')) return 'Failed'
    if (endEvent?.type.includes('completed')) return 'Completed'
    if (endEvent?.type.includes('received')) return 'Received'
    if (endEvent?.type.includes('cancelled')) return 'Cancelled'
    if (!endEvent) return 'In Progress'
    return formatEventType(endEvent.type).split(' ').pop() || 'Unknown'
  }

  return (
    <div className="border-t bg-muted/30 animate-in slide-in-from-top-2 duration-200">
      <div className="px-4 py-4">
        {/* Header with icon, name, duration, and close button */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            {renderCategoryIcon()}
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-base">{getDisplayName()}</h3>
                <Badge variant={getBadgeVariant()} className="text-xs">
                  {getStatusText()}
                </Badge>
              </div>
              {durationMs !== null && (
                <div className="flex items-center gap-1 mt-1 text-sm text-foreground">
                  <IconHourglass size={14} className="text-muted-foreground" />
                  <span className="font-mono font-medium">{formatDuration(durationMs)}</span>
                </div>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-muted transition-colors"
            aria-label="Close details"
          >
            <IconChevronDown size={16} />
          </button>
        </div>

        {/* Time details - Start and End timestamps */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4 p-3 bg-muted/50 rounded-lg">
          {/* Start Time */}
          {startEvent && (
            <div className="flex items-start gap-2">
              <IconPlayerPlay size={16} className="mt-0.5 text-green-500" />
              <div>
                <div className="text-xs text-muted-foreground">Start Time</div>
                <div className="font-mono text-sm font-medium">
                  {format(new Date(startEvent.timestamp), 'HH:mm:ss.SSS')}
                </div>
                <div className="font-mono text-xs text-muted-foreground">
                  +{formatDuration(startEvent.relativeTimeMs)}
                </div>
              </div>
            </div>
          )}

          {/* End Time */}
          {endEvent && (
            <div className="flex items-start gap-2">
              <IconPlayerStop size={16} className="mt-0.5 text-blue-500" />
              <div>
                <div className="text-xs text-muted-foreground">End Time</div>
                <div className="font-mono text-sm font-medium">
                  {format(new Date(endEvent.timestamp), 'HH:mm:ss.SSS')}
                </div>
                <div className="font-mono text-xs text-muted-foreground">
                  +{formatDuration(endEvent.relativeTimeMs)}
                </div>
              </div>
            </div>
          )}

          {/* Duration */}
          {durationMs !== null && (
            <div className="flex items-start gap-2">
              <IconClock size={16} className="mt-0.5 text-purple-500" />
              <div>
                <div className="text-xs text-muted-foreground">Duration</div>
                <div className="font-mono text-sm font-medium">
                  {formatDuration(durationMs)}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Step Input/Output (if available) */}
        {hasInputOutput(event, pairedEvent) ? (
          <div className="space-y-3 mb-4">
            {/* Input */}
            {hasInput(event) ? (
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1.5 uppercase tracking-wide">
                  Input
                </div>
                <pre className="text-xs bg-muted p-3 rounded-lg overflow-x-auto max-h-24 font-mono">
                  {JSON.stringify(event.data?.input ?? event.data?.args, null, 2)}
                </pre>
              </div>
            ) : null}

            {/* Output/Result */}
            {hasOutput(event, pairedEvent) ? (
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1.5 uppercase tracking-wide">
                  Output
                </div>
                <pre className="text-xs bg-muted p-3 rounded-lg overflow-x-auto max-h-24 font-mono">
                  {JSON.stringify(
                    event.data?.result ?? event.data?.output ??
                    pairedEvent?.data?.result ?? pairedEvent?.data?.output,
                    null, 2
                  )}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Additional details grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          {/* Sequence */}
          <div>
            <div className="text-xs text-muted-foreground">Sequence</div>
            <div className="font-mono">#{event.sequence}</div>
          </div>

          {/* Category */}
          <div>
            <div className="text-xs text-muted-foreground">Category</div>
            <div className="capitalize">{event.category.replace('_', ' ')}</div>
          </div>

          {/* Hook ID (if applicable) */}
          {event.data?.hook_id && event.category === 'hook' ? (
            <div>
              <div className="text-xs text-muted-foreground">Hook ID</div>
              <div className="font-mono truncate text-xs" title={String(event.data.hook_id)}>
                {String(event.data.hook_id)}
              </div>
            </div>
          ) : null}

          {/* Sleep Duration (if applicable) */}
          {event.data?.duration_seconds ? (
            <div>
              <div className="text-xs text-muted-foreground">Sleep Duration</div>
              <div className="font-mono">
                {formatDuration(Number(event.data.duration_seconds) * 1000)}
              </div>
            </div>
          ) : null}
        </div>

        {/* Error (if applicable) */}
        {(event.data?.error || pairedEvent?.data?.error) ? (
          <div className="mt-4">
            <div className="text-xs font-medium text-destructive mb-1.5 uppercase tracking-wide">
              Error
            </div>
            <div className="text-sm text-destructive font-mono bg-destructive/10 p-3 rounded-lg">
              {String(event.data?.error || pairedEvent?.data?.error)}
            </div>
          </div>
        ) : null}

        {/* Event ID - collapsed */}
        <div className="mt-4 pt-3 border-t text-xs text-muted-foreground">
          <span className="font-medium">Event ID:</span>{' '}
          <span className="font-mono">{event.event_id}</span>
        </div>
      </div>
    </div>
  )
}
