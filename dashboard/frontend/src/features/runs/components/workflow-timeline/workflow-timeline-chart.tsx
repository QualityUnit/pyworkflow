/**
 * D3-powered swim lane timeline chart for workflow events.
 * Each step/category gets its own horizontal lane.
 */

import { useRef, useEffect, useState, useMemo } from 'react'
import * as d3 from 'd3'
import type { TimelineEvent, ViewMode } from './timeline-types'
import {
  formatDuration,
  getNodeSymbol,
  pairEvents,
  createBarPath,
  extractLanes,
} from './timeline-utils'
import type { Event } from '@/api/types'

interface WorkflowTimelineChartProps {
  events: TimelineEvent[]
  rawEvents: Event[]
  totalDurationMs: number
  selectedEventId: string | null
  onEventClick: (eventId: string) => void
  onEventHover: (event: TimelineEvent | null) => void
  viewMode: ViewMode
}

const LANE_HEIGHT = 40
const MIN_HEIGHT = 120

export function WorkflowTimelineChart({
  events,
  rawEvents,
  totalDurationMs,
  selectedEventId,
  onEventClick,
  onEventHover,
  viewMode,
}: WorkflowTimelineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: MIN_HEIGHT })

  // Extract lanes from events
  const lanes = useMemo(() => extractLanes(rawEvents), [rawEvents])

  // Calculate event pairs for duration bars
  const eventPairs = useMemo(() => pairEvents(events), [events])

  // Calculate height based on number of lanes
  const chartHeight = useMemo(() => {
    const laneCount = lanes.length
    const height = laneCount * LANE_HEIGHT + 60 // 60 for margins and axis
    return Math.max(height, MIN_HEIGHT)
  }, [lanes])

  // Responsive sizing with resize observer
  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout>

    const observer = new ResizeObserver((entries) => {
      clearTimeout(timeoutId)
      timeoutId = setTimeout(() => {
        if (entries[0]) {
          const { width } = entries[0].contentRect
          setDimensions({
            width: Math.max(width, 400),
            height: chartHeight,
          })
        }
      }, 100)
    })

    if (containerRef.current) {
      observer.observe(containerRef.current)
    }
    return () => {
      clearTimeout(timeoutId)
      observer.disconnect()
    }
  }, [chartHeight])

  // D3 rendering
  useEffect(() => {
    if (!svgRef.current || events.length === 0) return

    const svg = d3.select(svgRef.current)
    const margin = { top: 15, right: 30, bottom: 35, left: 100 }
    const width = dimensions.width - margin.left - margin.right
    const height = dimensions.height - margin.top - margin.bottom

    // Clear previous render
    svg.selectAll('*').remove()

    // Main group with margin
    const g = svg
      .attr('width', dimensions.width)
      .attr('height', dimensions.height)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    // Y scale for lanes
    const yScale = d3
      .scaleBand<number>()
      .domain(lanes.map((_, i) => i))
      .range([0, height])
      .padding(0.2)

    // Time scale (X axis)
    const xScale = d3
      .scaleLinear()
      .domain([0, Math.max(totalDurationMs, 1000)])
      .range([0, width])

    // Draw lane backgrounds with alternating colors
    lanes.forEach((lane, i) => {
      const y = yScale(i) ?? 0
      const laneHeight = yScale.bandwidth()

      // Lane background
      g.append('rect')
        .attr('x', 0)
        .attr('y', y)
        .attr('width', width)
        .attr('height', laneHeight)
        .attr('fill', i % 2 === 0 ? 'var(--muted)' : 'transparent')
        .attr('opacity', 0.3)

      // Lane label
      g.append('text')
        .attr('x', -10)
        .attr('y', y + laneHeight / 2)
        .attr('text-anchor', 'end')
        .attr('dominant-baseline', 'middle')
        .attr('class', 'text-xs fill-muted-foreground')
        .text(lane.name.length > 12 ? lane.name.slice(0, 12) + '…' : lane.name)

      // Color indicator dot
      g.append('circle')
        .attr('cx', -margin.left + 15)
        .attr('cy', y + laneHeight / 2)
        .attr('r', 5)
        .attr('fill', lane.color)
    })

    // Draw duration bars for paired events
    eventPairs
      .filter((pair) => pair.endEvent && pair.durationMs && pair.durationMs > 0)
      .forEach((pair) => {
        const startX = xScale(pair.startEvent.relativeTimeMs)
        const endX = xScale(pair.endEvent!.relativeTimeMs)
        const y = yScale(pair.startEvent.laneIndex) ?? 0
        const laneHeight = yScale.bandwidth()
        const barHeight = Math.min(laneHeight * 0.5, 16)
        const barY = y + (laneHeight - barHeight) / 2

        // Duration bar with lane color
        g.append('rect')
          .attr('x', startX)
          .attr('y', barY)
          .attr('width', Math.max(endX - startX, 2))
          .attr('height', barHeight)
          .attr('rx', 3)
          .attr('fill', pair.startEvent.laneColor)
          .attr('opacity', 0.4)
          .attr('class', 'cursor-pointer')
          .on('click', () => onEventClick(pair.startEvent.event_id))
          .on('mouseenter', () => onEventHover(pair.startEvent))
          .on('mouseleave', () => onEventHover(null))

        // Duration label on bar (if wide enough)
        const barWidth = endX - startX
        if (barWidth > 50 && pair.durationMs) {
          g.append('text')
            .attr('x', startX + barWidth / 2)
            .attr('y', barY + barHeight / 2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('class', 'text-[10px] fill-foreground font-medium pointer-events-none')
            .text(formatDuration(pair.durationMs))
        }
      })

    // Symbol generator
    const symbolGenerator = d3.symbol().size(viewMode === 'compact' ? 80 : 120)

    // Event nodes group
    const nodesGroup = g.append('g').attr('class', 'event-nodes')

    // Draw event nodes
    events.forEach((event) => {
      const x = xScale(event.relativeTimeMs)
      const y = (yScale(event.laneIndex) ?? 0) + yScale.bandwidth() / 2
      const isSelected = event.event_id === selectedEventId
      const nodeSize = isSelected ? 1.3 : 1
      const symbol = getNodeSymbol(event.category)

      const nodeGroup = nodesGroup
        .append('g')
        .attr('transform', `translate(${x},${y})`)
        .attr('class', 'cursor-pointer')
        .on('click', (e) => {
          e.stopPropagation()
          onEventClick(event.event_id)
        })
        .on('mouseenter', () => onEventHover(event))
        .on('mouseleave', () => onEventHover(null))

      // Draw the shape based on category
      if (symbol === 'bar') {
        nodeGroup
          .append('path')
          .attr('d', createBarPath(16 * nodeSize, 8 * nodeSize))
          .attr('fill', event.laneColor)
          .attr('stroke', isSelected ? 'var(--ring)' : 'white')
          .attr('stroke-width', isSelected ? 2 : 1.5)
      } else if (symbol === 'double-circle') {
        nodeGroup
          .append('circle')
          .attr('r', 7 * nodeSize)
          .attr('fill', event.laneColor)
          .attr('stroke', isSelected ? 'var(--ring)' : 'white')
          .attr('stroke-width', isSelected ? 2 : 1.5)
        nodeGroup
          .append('circle')
          .attr('r', 3 * nodeSize)
          .attr('fill', 'white')
          .attr('fill-opacity', 0.8)
      } else {
        nodeGroup
          .append('path')
          .attr(
            'd',
            symbolGenerator.type(symbol).size((viewMode === 'compact' ? 80 : 120) * nodeSize * nodeSize)()
          )
          .attr('fill', event.laneColor)
          .attr('stroke', isSelected ? 'var(--ring)' : 'white')
          .attr('stroke-width', isSelected ? 2 : 1.5)
      }

      // Selection indicator
      if (isSelected) {
        nodeGroup
          .append('circle')
          .attr('r', 12)
          .attr('fill', 'none')
          .attr('stroke', event.laneColor)
          .attr('stroke-width', 2)
          .attr('stroke-opacity', 0.5)
          .attr('stroke-dasharray', '3,2')
      }
    })

    // Time axis at bottom
    const xAxis = d3
      .axisBottom(xScale)
      .ticks(Math.min(8, Math.floor(width / 100)))
      .tickFormat((d) => formatDuration(d as number))

    g.append('g')
      .attr('transform', `translate(0,${height})`)
      .attr('class', 'timeline-axis')
      .call(xAxis)
      .selectAll('text')
      .attr('class', 'text-xs fill-muted-foreground')

    g.selectAll('.timeline-axis path, .timeline-axis line').attr(
      'class',
      'stroke-border'
    )

    // Zoom behavior
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 8])
      .translateExtent([
        [-margin.left, 0],
        [dimensions.width, dimensions.height],
      ])
      .extent([
        [0, 0],
        [dimensions.width, dimensions.height],
      ])
      .on('zoom', (event) => {
        const newXScale = event.transform.rescaleX(xScale)

        // Update axis
        g.select<SVGGElement>('.timeline-axis').call(
          xAxis.scale(newXScale) as unknown as (
            selection: d3.Selection<SVGGElement, unknown, null, undefined>
          ) => void
        )

        // Update node positions (only X)
        nodesGroup.selectAll('g').attr('transform', (_, i) => {
          const e = events[i]
          const y = (yScale(e.laneIndex) ?? 0) + yScale.bandwidth() / 2
          return `translate(${newXScale(e.relativeTimeMs)},${y})`
        })

        // Update duration bars
        g.selectAll('rect').each(function () {
          const rect = d3.select(this)
          const x = parseFloat(rect.attr('data-start-x') || rect.attr('x'))
          const endX = parseFloat(rect.attr('data-end-x') || '0')
          if (endX > 0) {
            rect.attr('x', newXScale(x)).attr('width', newXScale(endX) - newXScale(x))
          }
        })
      })

    svg.call(zoom)

    // Double-click to reset zoom
    svg.on('dblclick.zoom', () => {
      svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity)
    })
  }, [
    events,
    eventPairs,
    lanes,
    dimensions,
    selectedEventId,
    totalDurationMs,
    viewMode,
    onEventClick,
    onEventHover,
  ])

  return (
    <div ref={containerRef} className="w-full overflow-hidden">
      <svg
        ref={svgRef}
        className="w-full"
        style={{ minHeight: `${chartHeight}px` }}
      />
    </div>
  )
}
