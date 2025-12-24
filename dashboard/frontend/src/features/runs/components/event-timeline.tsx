/**
 * Event timeline component for workflow runs.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { Event } from '@/api/types'

interface EventTimelineProps {
  events: Event[]
}

const eventTypeColors: Record<string, string> = {
  'workflow.started': 'bg-blue-500',
  'workflow.completed': 'bg-green-500',
  'workflow.failed': 'bg-red-500',
  'workflow.interrupted': 'bg-orange-500',
  'step.started': 'bg-blue-400',
  'step.completed': 'bg-green-400',
  'step.failed': 'bg-red-400',
  'step.retrying': 'bg-yellow-500',
  'sleep.started': 'bg-purple-400',
  'sleep.completed': 'bg-purple-500',
  'hook.created': 'bg-cyan-400',
  'hook.received': 'bg-cyan-500',
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString()
}

function getEventColor(type: string): string {
  return eventTypeColors[type] || 'bg-gray-400'
}

export function EventTimeline({ events }: EventTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No events recorded.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {events.map((event, index) => (
        <div key={event.event_id} className="flex gap-4">
          {/* Timeline line */}
          <div className="flex flex-col items-center">
            <div className={`w-3 h-3 rounded-full ${getEventColor(event.type)}`} />
            {index < events.length - 1 && (
              <div className="w-0.5 flex-1 bg-border mt-1" />
            )}
          </div>

          {/* Event content */}
          <Card className="flex-1 mb-2">
            <CardHeader className="py-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium">
                  {event.type}
                </CardTitle>
                <div className="flex items-center gap-2">
                  {event.sequence !== null && (
                    <Badge variant="outline" className="text-xs">
                      #{event.sequence}
                    </Badge>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {formatTime(event.timestamp)}
                  </span>
                </div>
              </div>
            </CardHeader>
            {Object.keys(event.data).length > 0 && (
              <CardContent className="py-2">
                <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
                  {JSON.stringify(event.data, null, 2)}
                </pre>
              </CardContent>
            )}
          </Card>
        </div>
      ))}
    </div>
  )
}
