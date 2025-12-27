/**
 * Timeline controls component with view toggle and legend.
 */

import { Button } from '@/components/ui/button'
import { Maximize2, Minimize2 } from 'lucide-react'
import type { ViewMode, LegendItem } from './timeline-types'
import { getLegendItems } from './timeline-utils'

interface TimelineControlsProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
}

export function TimelineControls({
  viewMode,
  onViewModeChange,
}: TimelineControlsProps) {
  return (
    <div className="flex items-center gap-1 border rounded-md p-0.5">
      <Button
        variant={viewMode === 'compact' ? 'secondary' : 'ghost'}
        size="sm"
        className="h-7 w-7 p-0"
        onClick={() => onViewModeChange('compact')}
        aria-label="Compact view"
      >
        <Minimize2 className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant={viewMode === 'detailed' ? 'secondary' : 'ghost'}
        size="sm"
        className="h-7 w-7 p-0"
        onClick={() => onViewModeChange('detailed')}
        aria-label="Detailed view"
      >
        <Maximize2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

/**
 * Legend component showing event category shapes.
 */
export function TimelineLegend() {
  const legendItems = getLegendItems()

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      {legendItems.map((item) => (
        <div key={item.category} className="flex items-center gap-1.5">
          <LegendShape item={item} />
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  )
}

/**
 * Render the shape icon for a legend item.
 */
function LegendShape({ item }: { item: LegendItem }) {
  const size = 14

  switch (item.shape) {
    case 'circle':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <circle cx="8" cy="8" r="5" fill={item.color} />
        </svg>
      )
    case 'square':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <rect x="3" y="3" width="10" height="10" rx="1" fill={item.color} />
        </svg>
      )
    case 'bar':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <rect x="2" y="5" width="12" height="6" rx="3" fill={item.color} />
        </svg>
      )
    case 'diamond':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <polygon points="8,2 14,8 8,14 2,8" fill={item.color} />
        </svg>
      )
    case 'double-circle':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <circle cx="8" cy="8" r="5" fill={item.color} />
          <circle cx="8" cy="8" r="2.5" fill="white" fillOpacity="0.8" />
        </svg>
      )
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 16 16">
          <circle cx="8" cy="8" r="5" fill={item.color} />
        </svg>
      )
  }
}
