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
  // Workflow events - Soft blue spectrum
  'workflow.started': '#93C5FD', // blue-300
  'workflow.completed': '#86EFAC', // green-300
  'workflow.failed': '#FCA5A5', // red-300
  'workflow.interrupted': '#FDBA74', // orange-300
  'workflow.cancelled': '#CBD5E1', // slate-300
  'workflow.paused': '#C4B5FD', // violet-300
  'workflow.resumed': '#93C5FD', // blue-300
  'workflow.continued_as_new': '#67E8F9', // cyan-300

  // Step events - Soft cyan/green spectrum
  'step.started': '#67E8F9', // cyan-300
  'step.completed': '#86EFAC', // green-300
  'step.failed': '#FCA5A5', // red-300
  'step.retrying': '#FDE047', // yellow-300
  'step.cancelled': '#CBD5E1', // slate-300

  // Sleep events - Soft purple spectrum
  'sleep.started': '#D8B4FE', // purple-300
  'sleep.completed': '#C4B5FD', // violet-300

  // Hook events - Soft orange spectrum
  'hook.created': '#FDBA74', // orange-300
  'hook.received': '#86EFAC', // green-300
  'hook.expired': '#FCA5A5', // red-300
  'hook.disposed': '#CBD5E1', // slate-300

  // Child workflow events - Soft indigo spectrum
  'child_workflow.started': '#A5B4FC', // indigo-300
  'child_workflow.completed': '#86EFAC', // green-300
  'child_workflow.failed': '#FCA5A5', // red-300
  'child_workflow.cancelled': '#CBD5E1', // slate-300

  // Cancellation
  'cancellation.requested': '#FCA5A5', // red-300
}

/**
 * Distinct color palette for individual steps/lanes.
 * Provides visually distinct colors for up to 12 different items.
 */
export const laneColors: string[] = [
  '#93C5FD', // blue-300
  '#86EFAC', // green-300
  '#FDBA74', // orange-300
  '#D8B4FE', // purple-300
  '#67E8F9', // cyan-300
  '#F9A8D4', // pink-300
  '#FDE047', // yellow-300
  '#A5B4FC', // indigo-300
  '#5EEAD4', // teal-300
  '#FDA4AF', // rose-300
  '#BEF264', // lime-300
  '#C4B5FD', // violet-300
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
 * Overhead statistics for the workflow.
 */
export interface OverheadStats {
  totalDurationMs: number
  stepDurationMs: number
  sleepDurationMs: number
  hookDurationMs: number
  overheadMs: number
  overheadPercent: number
}

/**
 * Overhead segment representing a gap in the timeline.
 */
export interface OverheadSegment {
  startMs: number
  endMs: number
  durationMs: number
  afterEvent: string // Description of what event this gap follows
}

/**
 * Calculate framework overhead.
 * Overhead = Total workflow time - (step durations + sleep durations + hook durations)
 *
 * Steps represent actual work being done.
 * Sleeps and hooks are expected waiting periods (not overhead).
 * Overhead represents framework processing time (event recording, task scheduling, etc.)
 */
export function calculateOverheadStats(pairs: EventPair[]): OverheadStats {
  let totalDurationMs = 0
  let stepDurationMs = 0
  let sleepDurationMs = 0
  let hookDurationMs = 0

  for (const pair of pairs) {
    if (!pair.endEvent || !pair.durationMs) continue

    const category = pair.startEvent.category

    if (category === 'workflow') {
      totalDurationMs = Math.max(totalDurationMs, pair.durationMs)
    } else if (category === 'step') {
      stepDurationMs += pair.durationMs
    } else if (category === 'sleep') {
      sleepDurationMs += pair.durationMs
    } else if (category === 'hook') {
      hookDurationMs += pair.durationMs
    }
    // child_workflow durations are not added since they're tracked separately
  }

  // Overhead = total - (steps + sleep + hooks)
  // This represents time spent on framework operations
  const workTime = stepDurationMs + sleepDurationMs + hookDurationMs
  const overheadMs = Math.max(0, totalDurationMs - workTime)
  const overheadPercent = totalDurationMs > 0 ? (overheadMs / totalDurationMs) * 100 : 0

  return {
    totalDurationMs,
    stepDurationMs,
    sleepDurationMs,
    hookDurationMs,
    overheadMs,
    overheadPercent,
  }
}

/**
 * Find overhead segments (gaps between events) for visualization.
 * Returns segments where no step/sleep/hook was actively running.
 */
export function findOverheadSegments(pairs: EventPair[]): OverheadSegment[] {
  // Get all completed pairs sorted by start time
  const completedPairs = pairs
    .filter((p) => p.endEvent && p.durationMs && p.startEvent.category !== 'workflow')
    .sort((a, b) => a.startEvent.relativeTimeMs - b.startEvent.relativeTimeMs)

  if (completedPairs.length === 0) return []

  // Find the workflow pair for total duration
  const workflowPair = pairs.find((p) => p.startEvent.category === 'workflow' && p.endEvent)
  const workflowEndMs = workflowPair?.endEvent?.relativeTimeMs ??
    Math.max(...completedPairs.map((p) => p.endEvent!.relativeTimeMs))

  const segments: OverheadSegment[] = []

  // Check for initial overhead (before first event)
  const firstPair = completedPairs[0]
  if (firstPair.startEvent.relativeTimeMs > 10) { // >10ms threshold
    segments.push({
      startMs: 0,
      endMs: firstPair.startEvent.relativeTimeMs,
      durationMs: firstPair.startEvent.relativeTimeMs,
      afterEvent: 'Workflow started',
    })
  }

  // Build timeline of active periods
  type TimePoint = { time: number; type: 'start' | 'end'; name: string }
  const points: TimePoint[] = []

  for (const pair of completedPairs) {
    const name = pair.startEvent.data?.step_name
      ? String(pair.startEvent.data.step_name)
      : pair.startEvent.laneName
    points.push({ time: pair.startEvent.relativeTimeMs, type: 'start', name })
    points.push({ time: pair.endEvent!.relativeTimeMs, type: 'end', name })
  }

  points.sort((a, b) => a.time - b.time || (a.type === 'start' ? -1 : 1))

  // Find gaps where nothing is running
  let activeCount = 0
  let lastEndTime = 0
  let lastEndName = ''

  for (const point of points) {
    if (point.type === 'start') {
      // Check for gap before this start
      if (activeCount === 0 && point.time - lastEndTime > 10) { // >10ms threshold
        segments.push({
          startMs: lastEndTime,
          endMs: point.time,
          durationMs: point.time - lastEndTime,
          afterEvent: lastEndName || 'Previous event',
        })
      }
      activeCount++
    } else {
      activeCount--
      if (activeCount === 0) {
        lastEndTime = point.time
        lastEndName = point.name
      }
    }
  }

  // Check for final overhead (after last event)
  if (lastEndTime < workflowEndMs - 10) { // >10ms threshold
    segments.push({
      startMs: lastEndTime,
      endMs: workflowEndMs,
      durationMs: workflowEndMs - lastEndTime,
      afterEvent: lastEndName || 'Last event',
    })
  }

  return segments
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
      color: '#93C5FD',
      shape: 'bar',
    },
    {
      category: 'step',
      label: 'Step',
      color: '#67E8F9',
      shape: 'bar',
    },
    {
      category: 'sleep',
      label: 'Sleep',
      color: '#D8B4FE',
      shape: 'bar',
    },
    {
      category: 'hook',
      label: 'Hook',
      color: '#FDBA74',
      shape: 'bar',
    },
    {
      category: 'child_workflow',
      label: 'Child WF',
      color: '#A5B4FC',
      shape: 'bar',
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
 * Get SVG path data for category icons (exact paths from Tabler Icons).
 * These paths are sized for a 24x24 viewBox.
 * Returns an array of path strings for multi-path icons.
 */
export function getCategoryIconPaths(category: EventCategory): string[] {
  switch (category) {
    case 'workflow':
      // IconRoute - represents workflow path
      return [
        'M3 19a2 2 0 1 0 4 0a2 2 0 0 0 -4 0',
        'M19 7a2 2 0 1 0 0 -4a2 2 0 0 0 0 4z',
        'M11 19h5.5a3.5 3.5 0 0 0 0 -7h-8a3.5 3.5 0 0 1 0 -7h4.5',
      ]
    case 'step':
      // IconPlayerTrackNext - represents a step forward
      return [
        'M3 5v14l8 -7z',
        'M14 5v14l8 -7z',
      ]
    case 'sleep':
      // IconMoon
      return [
        'M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z',
      ]
    case 'hook':
      // IconWebhook
      return [
        'M4.876 13.61a4 4 0 1 0 6.124 3.39h6',
        'M15.066 20.502a4 4 0 1 0 1.934 -7.502c-.706 0 -1.424 .179 -2 .5l-3 -5.5',
        'M16 8a4 4 0 1 0 -8 0c0 1.506 .77 2.818 2 3.5l-3 5.5',
      ]
    case 'child_workflow':
      // IconGitBranch - represents child workflow branching
      return [
        'M7 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
        'M7 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
        'M17 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
        'M7 8l0 8',
        'M9 18h6a2 2 0 0 0 2 -2v-5',
        'M14 14l3 -3l3 3',
      ]
    default:
      return [
        'M3 19a2 2 0 1 0 4 0a2 2 0 0 0 -4 0',
        'M19 7a2 2 0 1 0 0 -4a2 2 0 0 0 0 4z',
        'M11 19h5.5a3.5 3.5 0 0 0 0 -7h-8a3.5 3.5 0 0 1 0 -7h4.5',
      ]
  }
}

/**
 * Get SVG path data for category icons as a single combined path.
 * @deprecated Use getCategoryIconPaths() for proper multi-path rendering.
 */
export function getCategoryIconPath(category: EventCategory): string {
  return getCategoryIconPaths(category).join(' ')
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
