/**
 * Utility functions for the workflow timeline visualization.
 */

import * as d3 from 'd3'
import type { Event } from '@/api/types'
import type {
  EventCategory,
  TimelineEvent,
  EventPair,
  LegendItem,
  Lane,
} from './timeline-types'

/**
 * Color mapping by event type.
 * Uses Tailwind CSS colors for consistency with the design system.
 */
export const eventColors: Record<string, string> = {
  // Workflow events - Blue spectrum
  'workflow.started': '#3b82f6', // blue-500
  'workflow.completed': '#22c55e', // green-500
  'workflow.failed': '#ef4444', // red-500
  'workflow.interrupted': '#f97316', // orange-500
  'workflow.cancelled': '#64748b', // slate-500
  'workflow.paused': '#8b5cf6', // violet-500
  'workflow.resumed': '#3b82f6', // blue-500
  'workflow.continued_as_new': '#06b6d4', // cyan-500

  // Step events - Cyan/Green spectrum
  'step.started': '#06b6d4', // cyan-500
  'step.completed': '#22c55e', // green-500
  'step.failed': '#ef4444', // red-500
  'step.retrying': '#eab308', // yellow-500
  'step.cancelled': '#64748b', // slate-500

  // Sleep events - Purple spectrum
  'sleep.started': '#a855f7', // purple-500
  'sleep.completed': '#7c3aed', // violet-600

  // Hook events - Orange spectrum
  'hook.created': '#f97316', // orange-500
  'hook.received': '#22c55e', // green-500
  'hook.expired': '#ef4444', // red-500
  'hook.disposed': '#64748b', // slate-500

  // Child workflow events - Indigo spectrum
  'child_workflow.started': '#6366f1', // indigo-500
  'child_workflow.completed': '#22c55e', // green-500
  'child_workflow.failed': '#ef4444', // red-500
  'child_workflow.cancelled': '#64748b', // slate-500

  // Cancellation
  'cancellation.requested': '#ef4444', // red-500
}

/**
 * Distinct color palette for individual steps/lanes.
 * Provides visually distinct colors for up to 12 different items.
 */
export const laneColors: string[] = [
  '#3b82f6', // blue-500
  '#22c55e', // green-500
  '#f97316', // orange-500
  '#a855f7', // purple-500
  '#06b6d4', // cyan-500
  '#ec4899', // pink-500
  '#eab308', // yellow-500
  '#6366f1', // indigo-500
  '#14b8a6', // teal-500
  '#f43f5e', // rose-500
  '#84cc16', // lime-500
  '#8b5cf6', // violet-500
]

/**
 * Get a consistent color for a lane based on its index.
 */
export function getLaneColor(index: number): string {
  return laneColors[index % laneColors.length]
}

/**
 * Default color for unknown event types.
 */
const DEFAULT_COLOR = '#9ca3af' // gray-400

/**
 * Get the category of an event based on its type.
 */
export function getEventCategory(type: string): EventCategory {
  if (type.startsWith('workflow.')) return 'workflow'
  if (type.startsWith('step.')) return 'step'
  if (type.startsWith('sleep.')) return 'sleep'
  if (type.startsWith('hook.')) return 'hook'
  if (type.startsWith('child_workflow.')) return 'child_workflow'
  return 'workflow' // Default fallback
}

/**
 * Get the color for an event type.
 */
export function getEventColor(type: string): string {
  return eventColors[type] ?? DEFAULT_COLOR
}

/**
 * Get the D3 symbol type for an event category.
 */
export function getNodeSymbol(
  category: EventCategory
): d3.SymbolType | 'bar' | 'double-circle' {
  switch (category) {
    case 'workflow':
      return d3.symbolCircle
    case 'step':
      return d3.symbolSquare
    case 'sleep':
      return 'bar'
    case 'hook':
      return d3.symbolDiamond
    case 'child_workflow':
      return 'double-circle'
    default:
      return d3.symbolCircle
  }
}

/**
 * Get lane identifier for an event.
 * Groups events by their logical entity (step name, sleep id, etc.)
 */
function getEventLaneId(event: Event): string {
  const category = getEventCategory(event.type)

  switch (category) {
    case 'workflow':
      return 'workflow'
    case 'step':
      return `step:${event.data?.step_name ?? event.data?.step_id ?? 'unknown'}`
    case 'sleep':
      return `sleep:${event.data?.sleep_id ?? 'sleep'}`
    case 'hook':
      return `hook:${event.data?.hook_id ?? 'hook'}`
    case 'child_workflow':
      return `child:${event.data?.child_run_id ?? event.data?.workflow_name ?? 'child'}`
    default:
      return 'other'
  }
}

/**
 * Get display name for a lane.
 */
function getLaneName(laneId: string, event: Event): string {
  if (laneId === 'workflow') return 'Workflow'
  if (laneId.startsWith('step:')) {
    return String(event.data?.step_name ?? laneId.replace('step:', ''))
  }
  if (laneId.startsWith('sleep:')) return 'Sleep'
  if (laneId.startsWith('hook:')) {
    return String(event.data?.hook_id ?? 'Hook')
  }
  if (laneId.startsWith('child:')) {
    return String(event.data?.workflow_name ?? 'Child Workflow')
  }
  return laneId
}

/**
 * Extract unique lanes from events.
 */
export function extractLanes(events: Event[]): Lane[] {
  const laneMap = new Map<string, { name: string; category: EventCategory; firstEvent: Event }>()

  // Workflow lane always first
  laneMap.set('workflow', { name: 'Workflow', category: 'workflow', firstEvent: events[0] })

  for (const event of events) {
    const laneId = getEventLaneId(event)
    if (!laneMap.has(laneId)) {
      laneMap.set(laneId, {
        name: getLaneName(laneId, event),
        category: getEventCategory(event.type),
        firstEvent: event,
      })
    }
  }

  // Convert to array and assign indices/colors
  const lanes: Lane[] = []
  let index = 0

  for (const [id, info] of laneMap) {
    lanes.push({
      id,
      name: info.name,
      color: getLaneColor(index),
      index,
      category: info.category,
    })
    index++
  }

  return lanes
}

/**
 * Process raw events into timeline-ready format.
 */
export function processEventsForTimeline(
  events: Event[],
  workflowStartTime: Date | null
): TimelineEvent[] {
  if (!workflowStartTime || events.length === 0) return []

  const startTimeMs = workflowStartTime.getTime()
  const lanes = extractLanes(events)
  const laneMap = new Map(lanes.map(l => [l.id, l]))

  return events
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
    .map((event) => {
      const eventTimeMs = new Date(event.timestamp).getTime()
      const laneId = getEventLaneId(event)
      const lane = laneMap.get(laneId) ?? lanes[0]

      return {
        ...event,
        relativeTimeMs: Math.max(0, eventTimeMs - startTimeMs),
        category: getEventCategory(event.type),
        color: getEventColor(event.type),
        laneId: lane.id,
        laneName: lane.name,
        laneColor: lane.color,
        laneIndex: lane.index,
      }
    })
}

/**
 * Find the workflow start time from events.
 */
export function findWorkflowStartTime(events: Event[]): Date | null {
  const startEvent = events.find((e) => e.type === 'workflow.started')
  if (startEvent) {
    return new Date(startEvent.timestamp)
  }
  // Fallback to earliest event
  if (events.length > 0) {
    const sorted = [...events].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )
    return new Date(sorted[0].timestamp)
  }
  return null
}

/**
 * Calculate total duration of the workflow.
 */
export function calculateTotalDuration(events: TimelineEvent[]): number {
  if (events.length === 0) return 0
  return Math.max(...events.map((e) => e.relativeTimeMs))
}

/**
 * Pair start/end events for connecting lines.
 */
export function pairEvents(events: TimelineEvent[]): EventPair[] {
  const pairs: EventPair[] = []
  const startedEvents = new Map<string, TimelineEvent>()

  for (const event of events) {
    const eventKey = getEventPairKey(event)
    if (!eventKey) continue

    if (isStartEvent(event.type)) {
      startedEvents.set(eventKey, event)
    } else if (isEndEvent(event.type)) {
      const startEvent = startedEvents.get(eventKey)
      if (startEvent) {
        pairs.push({
          startEvent,
          endEvent: event,
          durationMs: event.relativeTimeMs - startEvent.relativeTimeMs,
        })
        startedEvents.delete(eventKey)
      }
    }
  }

  // Add unpaired start events (still in progress)
  for (const startEvent of startedEvents.values()) {
    pairs.push({ startEvent })
  }

  return pairs
}

/**
 * Get the key for pairing events (e.g., step_id for steps).
 */
function getEventPairKey(event: TimelineEvent): string | null {
  const type = event.type

  if (type.startsWith('step.')) {
    return `step:${event.data?.step_id ?? event.data?.step_name ?? ''}`
  }
  if (type.startsWith('sleep.')) {
    return `sleep:${event.data?.sleep_id ?? ''}`
  }
  if (type.startsWith('hook.')) {
    return `hook:${event.data?.hook_id ?? ''}`
  }
  if (type.startsWith('workflow.')) {
    return `workflow:${event.run_id}`
  }
  if (type.startsWith('child_workflow.')) {
    return `child:${event.data?.child_run_id ?? ''}`
  }

  return null
}

/**
 * Check if an event type is a "start" event.
 */
function isStartEvent(type: string): boolean {
  return (
    type.endsWith('.started') ||
    type.endsWith('.created') ||
    type === 'cancellation.requested'
  )
}

/**
 * Check if an event type is an "end" event.
 */
function isEndEvent(type: string): boolean {
  return (
    type.endsWith('.completed') ||
    type.endsWith('.failed') ||
    type.endsWith('.cancelled') ||
    type.endsWith('.received') ||
    type.endsWith('.expired') ||
    type.endsWith('.disposed')
  )
}

/**
 * Format duration in human-readable form.
 */
export function formatDuration(ms: number): string {
  if (ms < 0) return '0ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(1)
  return `${minutes}m ${seconds}s`
}

/**
 * Format event type for display.
 */
export function formatEventType(type: string): string {
  return type
    .replace(/_/g, ' ')
    .replace(/\./g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (l) => l.toUpperCase())
}

/**
 * Get legend items for the timeline.
 */
export function getLegendItems(): LegendItem[] {
  return [
    {
      category: 'workflow',
      label: 'Workflow',
      color: '#3b82f6',
      shape: 'circle',
    },
    {
      category: 'step',
      label: 'Step',
      color: '#06b6d4',
      shape: 'square',
    },
    {
      category: 'sleep',
      label: 'Sleep',
      color: '#a855f7',
      shape: 'bar',
    },
    {
      category: 'hook',
      label: 'Hook',
      color: '#f97316',
      shape: 'diamond',
    },
    {
      category: 'child_workflow',
      label: 'Child WF',
      color: '#6366f1',
      shape: 'double-circle',
    },
  ]
}

/**
 * Create SVG path for bar/pill shape.
 */
export function createBarPath(width: number = 16, height: number = 8): string {
  const r = height / 2
  return `M${-width / 2},${-r} h${width - r} a${r},${r} 0 0 1 0,${height} h${-(width - r)} a${r},${r} 0 0 1 0,${-height} Z`
}

/**
 * Create SVG path for double circle shape.
 */
export function createDoubleCirclePath(
  outerRadius: number = 8,
  innerRadius: number = 4
): string {
  // Outer circle
  const outer = `M${outerRadius},0 A${outerRadius},${outerRadius} 0 1 1 ${-outerRadius},0 A${outerRadius},${outerRadius} 0 1 1 ${outerRadius},0`
  // Inner circle (counter-clockwise for hole)
  const inner = `M${innerRadius},0 A${innerRadius},${innerRadius} 0 1 0 ${-innerRadius},0 A${innerRadius},${innerRadius} 0 1 0 ${innerRadius},0`
  return `${outer} ${inner}`
}

/**
 * Debounce function for resize handlers.
 */
export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>
  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(() => fn(...args), delay)
  }
}
