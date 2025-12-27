/**
 * TypeScript types for the workflow timeline visualization.
 */

import type { Event } from '@/api/types'

/**
 * Event categories for visual differentiation.
 * Each category uses a different shape in the timeline.
 */
export type EventCategory =
  | 'workflow'
  | 'step'
  | 'sleep'
  | 'hook'
  | 'child_workflow'

/**
 * Extended event interface with timeline-specific properties.
 */
export interface TimelineEvent extends Event {
  /** Milliseconds from workflow start */
  relativeTimeMs: number
  /** Event category for shape/color mapping */
  category: EventCategory
  /** Color to render this event */
  color: string
  /** ID of paired event (e.g., start -> end) */
  pairedEventId?: string
  /** Duration in milliseconds (for completed events) */
  durationMs?: number
  /** Lane identifier for swim lane placement */
  laneId: string
  /** Lane display name */
  laneName: string
  /** Lane color (distinct per lane) */
  laneColor: string
  /** Lane index for Y position */
  laneIndex: number
}

/**
 * Lane information for swim lane layout.
 */
export interface Lane {
  id: string
  name: string
  color: string
  index: number
  category: EventCategory
}

/**
 * Paired events for drawing connections (start -> end).
 */
export interface EventPair {
  startEvent: TimelineEvent
  endEvent?: TimelineEvent
  durationMs?: number
}

/**
 * Timeline view modes.
 */
export type ViewMode = 'compact' | 'detailed'

/**
 * Timeline dimensions configuration.
 */
export interface TimelineDimensions {
  width: number
  height: number
  margin: {
    top: number
    right: number
    bottom: number
    left: number
  }
}

/**
 * Zoom state for the timeline.
 */
export interface ZoomState {
  scale: number
  translateX: number
  translateY: number
}

/**
 * Legend item for event category display.
 */
export interface LegendItem {
  category: EventCategory
  label: string
  color: string
  shape: 'circle' | 'square' | 'bar' | 'diamond' | 'double-circle'
}
