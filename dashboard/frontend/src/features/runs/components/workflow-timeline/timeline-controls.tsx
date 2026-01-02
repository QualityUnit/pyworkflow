/**
 * Timeline controls component with view toggle and legend.
 */

import { Button } from '@/components/ui/button'
import { Maximize2, Minimize2 } from 'lucide-react'
import {
  IconRoute,
  IconPlayerTrackNext,
  IconMoon,
  IconWebhook,
  IconGitBranch,
} from '@tabler/icons-react'
import type { ViewMode, LegendItem, EventCategory } from './timeline-types'
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
 * Get the icon component for a category.
 */
function getCategoryIconComponent(category: EventCategory, color: string, size: number = 14) {
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

/**
 * Render the shape icon for a legend item.
 */
function LegendShape({ item }: { item: LegendItem }) {
  return getCategoryIconComponent(item.category, item.color, 14)
}
