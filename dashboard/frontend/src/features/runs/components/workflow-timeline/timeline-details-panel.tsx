/**
 * Collapsible details panel for selected timeline event.
 */

import { format } from 'date-fns'
import { Badge } from '@/components/ui/badge'
import { ChevronDown } from 'lucide-react'
import type { TimelineEvent } from './timeline-types'
import { formatDuration, formatEventType } from './timeline-utils'

interface TimelineDetailsPanelProps {
  event: TimelineEvent | null
  pairedEvent?: TimelineEvent | null
  onClose: () => void
}

export function TimelineDetailsPanel({
  event,
  pairedEvent,
  onClose,
}: TimelineDetailsPanelProps) {
  if (!event) return null

  const durationMs = pairedEvent
    ? Math.abs(
        new Date(pairedEvent.timestamp).getTime() -
          new Date(event.timestamp).getTime()
      )
    : null

  // Get badge variant based on event type
  const getBadgeVariant = (): 'default' | 'secondary' | 'destructive' | 'outline' => {
    if (event.type.includes('failed') || event.type.includes('expired')) {
      return 'destructive'
    }
    if (event.type.includes('completed') || event.type.includes('received')) {
      return 'default'
    }
    if (event.type.includes('started') || event.type.includes('created')) {
      return 'secondary'
    }
    return 'outline'
  }

  // Get shape icon for the event
  const getShapeIcon = () => {
    switch (event.category) {
      case 'workflow':
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <circle cx="8" cy="8" r="6" fill={event.color} />
          </svg>
        )
      case 'step':
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <rect x="3" y="3" width="10" height="10" rx="1" fill={event.color} />
          </svg>
        )
      case 'sleep':
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <rect x="2" y="5" width="12" height="6" rx="3" fill={event.color} />
          </svg>
        )
      case 'hook':
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <polygon points="8,2 14,8 8,14 2,8" fill={event.color} />
          </svg>
        )
      case 'child_workflow':
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <circle cx="8" cy="8" r="6" fill={event.color} />
            <circle cx="8" cy="8" r="3" fill="white" fillOpacity="0.8" />
          </svg>
        )
      default:
        return (
          <svg className="w-4 h-4" viewBox="0 0 16 16">
            <circle cx="8" cy="8" r="6" fill={event.color} />
          </svg>
        )
    }
  }

  return (
    <div className="border-t bg-muted/30 animate-in slide-in-from-top-2 duration-200">
      <div className="px-4 py-3">
        {/* Header with close button */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {getShapeIcon()}
            <Badge variant={getBadgeVariant()}>
              {formatEventType(event.type)}
            </Badge>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-muted transition-colors"
            aria-label="Close details"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>

        {/* Details grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {/* Timestamp */}
          <div>
            <div className="text-xs text-muted-foreground mb-1">Timestamp</div>
            <div className="font-mono text-sm">
              {format(new Date(event.timestamp), 'HH:mm:ss.SSS')}
            </div>
          </div>

          {/* Relative Time */}
          <div>
            <div className="text-xs text-muted-foreground mb-1">
              Relative Time
            </div>
            <div className="font-mono text-sm">
              +{formatDuration(event.relativeTimeMs)}
            </div>
          </div>

          {/* Duration (if available) */}
          {durationMs !== null ? (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Duration</div>
              <div className="font-mono text-sm">{formatDuration(durationMs)}</div>
            </div>
          ) : null}

          {/* Sequence */}
          <div>
            <div className="text-xs text-muted-foreground mb-1">Sequence</div>
            <div className="font-mono text-sm">#{event.sequence}</div>
          </div>

          {/* Step Name (if applicable) */}
          {event.data?.step_name ? (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Step</div>
              <div className="font-mono text-sm">
                {String(event.data.step_name)}
              </div>
            </div>
          ) : null}

          {/* Hook Name (if applicable) */}
          {event.data?.hook_id ? (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Hook ID</div>
              <div className="font-mono text-sm truncate" title={String(event.data.hook_id)}>
                {String(event.data.hook_id)}
              </div>
            </div>
          ) : null}

          {/* Sleep Duration (if applicable) */}
          {event.data?.duration_seconds ? (
            <div>
              <div className="text-xs text-muted-foreground mb-1">
                Sleep Duration
              </div>
              <div className="font-mono text-sm">
                {formatDuration(Number(event.data.duration_seconds) * 1000)}
              </div>
            </div>
          ) : null}

          {/* Error (if applicable) */}
          {event.data?.error ? (
            <div className="col-span-full">
              <div className="text-xs text-muted-foreground mb-1">Error</div>
              <div className="text-sm text-destructive font-mono bg-destructive/10 p-2 rounded">
                {String(event.data.error)}
              </div>
            </div>
          ) : null}
        </div>

        {/* Event ID */}
        <div className="mt-3 pt-3 border-t">
          <div className="text-xs text-muted-foreground mb-1">Event ID</div>
          <div className="font-mono text-xs text-muted-foreground">
            {event.event_id}
          </div>
        </div>

        {/* Full event data */}
        {Object.keys(event.data).length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-muted-foreground mb-1">Event Data</div>
            <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-32">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
