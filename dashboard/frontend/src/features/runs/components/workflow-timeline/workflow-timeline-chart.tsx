/**
 * D3-powered swim lane timeline chart for workflow events.
 * Each step/category gets its own horizontal lane.
 */

import { useRef, useEffect, useState, useMemo } from 'react'
import * as d3 from 'd3'
import type { TimelineEvent, ViewMode } from './timeline-types'
import {
  formatDuration,
  pairEvents,
  extractLanes,
  formatEventType,
  getCategoryIconPaths,
  type OverheadSegment,
} from './timeline-utils'
import type { Event } from '@/api/types'

interface WorkflowTimelineChartProps {
  events: TimelineEvent[]
  rawEvents: Event[]
  totalDurationMs: number
  selectedEventId: string | null
  onEventClick: (eventId: string) => void
  onEventHover: (event: TimelineEvent | null, position?: { x: number; y: number }) => void
  viewMode: ViewMode
  overheadSegments?: OverheadSegment[]
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
  overheadSegments = [],
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

    // Add clip path for zoom content
    svg
      .append('defs')
      .append('clipPath')
      .attr('id', 'chart-clip')
      .append('rect')
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', width)
      .attr('height', height)

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
      .padding(0.15)

    // Time scale (X axis)
    const xScale = d3
      .scaleLinear()
      .domain([0, Math.max(totalDurationMs, 1000)])
      .range([0, width])

    // Static elements group (lane labels - not affected by zoom)
    const staticGroup = g.append('g').attr('class', 'static-elements')

    // Draw lane labels (static)
    lanes.forEach((lane, i) => {
      const y = yScale(i) ?? 0
      const laneHeight = yScale.bandwidth()

      // Lane label
      staticGroup
        .append('text')
        .attr('x', -10)
        .attr('y', y + laneHeight / 2)
        .attr('text-anchor', 'end')
        .attr('dominant-baseline', 'middle')
        .attr('class', 'text-xs fill-muted-foreground')
        .text(lane.name.length > 12 ? lane.name.slice(0, 12) + '…' : lane.name)

      // Color indicator dot
      staticGroup
        .append('circle')
        .attr('cx', -margin.left + 15)
        .attr('cy', y + laneHeight / 2)
        .attr('r', 5)
        .attr('fill', lane.color)
    })

    // Zoomable content group with clip path
    const zoomGroup = g
      .append('g')
      .attr('class', 'zoom-content')
      .attr('clip-path', 'url(#chart-clip)')

    // Draw lane backgrounds with alternating colors
    const laneBgGroup = zoomGroup.append('g').attr('class', 'lane-backgrounds')
    lanes.forEach((_, i) => {
      const y = yScale(i) ?? 0
      const laneHeight = yScale.bandwidth()

      laneBgGroup
        .append('rect')
        .attr('class', 'lane-bg')
        .attr('x', 0)
        .attr('y', y)
        .attr('width', width)
        .attr('height', laneHeight)
        .attr('fill', i % 2 === 0 ? 'var(--muted)' : 'transparent')
        .attr('opacity', 0.3)
    })

    // Vertical grid lines
    const gridGroup = zoomGroup.append('g').attr('class', 'grid-lines')
    const tickCount = Math.min(8, Math.floor(width / 100))
    const gridTicks = xScale.ticks(tickCount)
    gridTicks.forEach((tick: number) => {
      gridGroup
        .append('line')
        .attr('class', 'grid-line')
        .attr('x1', xScale(tick))
        .attr('x2', xScale(tick))
        .attr('y1', 0)
        .attr('y2', height)
        .attr('stroke', 'var(--border)')
        .attr('stroke-opacity', 0.3)
        .attr('stroke-dasharray', '2,2')
        .attr('data-time', tick)
    })

    // Overhead segments group (hatched areas representing framework overhead)
    const overheadGroup = zoomGroup.append('g').attr('class', 'overhead-segments')

    // Create a hatched pattern for overhead visualization
    const defs = svg.select('defs')
    defs
      .append('pattern')
      .attr('id', 'overhead-pattern')
      .attr('patternUnits', 'userSpaceOnUse')
      .attr('width', 8)
      .attr('height', 8)
      .attr('patternTransform', 'rotate(45)')
      .append('line')
      .attr('x1', 0)
      .attr('y1', 0)
      .attr('x2', 0)
      .attr('y2', 8)
      .attr('stroke', 'var(--destructive)')
      .attr('stroke-width', 2)
      .attr('stroke-opacity', 0.3)

    // Draw overhead segments as hatched bars
    overheadSegments.forEach((segment) => {
      const startX = xScale(segment.startMs)
      const endX = xScale(segment.endMs)
      const segmentWidth = Math.max(endX - startX, 2)

      // Only draw if segment is visible (>2px)
      if (segmentWidth > 2) {
        overheadGroup
          .append('rect')
          .attr('class', 'overhead-bar')
          .attr('x', startX)
          .attr('y', 0)
          .attr('width', segmentWidth)
          .attr('height', height)
          .attr('fill', 'url(#overhead-pattern)')
          .attr('data-start-time', segment.startMs)
          .attr('data-end-time', segment.endMs)
          .attr('pointer-events', 'none')

        // Add a small label at the top if segment is wide enough
        if (segmentWidth > 40) {
          overheadGroup
            .append('text')
            .attr('class', 'overhead-label')
            .attr('x', startX + segmentWidth / 2)
            .attr('y', 10)
            .attr('text-anchor', 'middle')
            .attr('fill', 'var(--destructive)')
            .attr('font-size', '9px')
            .attr('font-weight', '500')
            .attr('opacity', 0.7)
            .attr('data-start-time', segment.startMs)
            .attr('data-end-time', segment.endMs)
            .text(`+${formatDuration(segment.durationMs)}`)
        }
      }
    })

    // Duration bars group
    const barsGroup = zoomGroup.append('g').attr('class', 'duration-bars')

    // Draw duration bars for paired events (main visualization)
    eventPairs
      .filter((pair) => pair.endEvent && pair.durationMs && pair.durationMs > 0)
      .forEach((pair) => {
        const startTime = pair.startEvent.relativeTimeMs
        const endTime = pair.endEvent!.relativeTimeMs
        const startX = xScale(startTime)
        const endX = xScale(endTime)
        const y = yScale(pair.startEvent.laneIndex) ?? 0
        const laneHeight = yScale.bandwidth()
        const barHeight = Math.min(laneHeight * 0.7, 24)
        const barY = y + (laneHeight - barHeight) / 2
        const barWidth = Math.max(endX - startX, 8)
        const isSelected = pair.startEvent.event_id === selectedEventId || pair.endEvent?.event_id === selectedEventId

        // Create bar group for this pair
        const barGroup = barsGroup.append('g').attr('class', 'bar-group')

        // Duration bar with lane color - rounded pill style
        barGroup
          .append('rect')
          .attr('class', 'duration-bar')
          .attr('x', startX)
          .attr('y', barY)
          .attr('width', barWidth)
          .attr('height', barHeight)
          .attr('rx', 6)
          .attr('fill', pair.startEvent.laneColor)
          .attr('opacity', isSelected ? 0.9 : 0.7)
          .attr('stroke', isSelected ? 'var(--ring)' : 'none')
          .attr('stroke-width', isSelected ? 2 : 0)
          .attr('cursor', 'pointer')
          .attr('data-start-time', startTime)
          .attr('data-end-time', endTime)
          .attr('data-bar-y', barY)
          .attr('data-bar-height', barHeight)
          .on('click', () => onEventClick(pair.startEvent.event_id))
          .on('mouseenter', function (this: SVGRectElement, e: MouseEvent) {
            const [px, py] = d3.pointer(e, containerRef.current)
            onEventHover(pair.startEvent, { x: px, y: py })
            d3.select(this).attr('opacity', 0.9)
          })
          .on('mouseleave', function (this: SVGRectElement) {
            onEventHover(null)
            d3.select(this).attr('opacity', isSelected ? 0.9 : 0.7)
          })

        // Label inside bar - show step name or event type
        const labelText = pair.startEvent.data?.step_name
          ? String(pair.startEvent.data.step_name)
          : formatEventType(pair.startEvent.type).split(' ')[0]

        // Icon size
        const iconSize = Math.min(barHeight - 4, 14)
        const iconPadding = 4

        // Add category icon at the left of the bar (if bar is wide enough)
        if (barWidth > 30) {
          const iconGroup = barGroup
            .append('g')
            .attr('class', 'bar-icon')
            .attr('transform', `translate(${startX + iconPadding + iconSize / 2}, ${barY + barHeight / 2})`)
            .attr('pointer-events', 'none')
            .attr('data-start-time', startTime)
            .attr('data-end-time', endTime)

          // Draw each path of the icon (Tabler icons use multiple paths)
          const iconPaths = getCategoryIconPaths(pair.startEvent.category)
          iconPaths.forEach((pathData) => {
            iconGroup
              .append('path')
              .attr('d', pathData)
              .attr('transform', `scale(${iconSize / 24}) translate(-12, -12)`)
              .attr('fill', 'none')
              .attr('stroke', 'var(--foreground)')
              .attr('stroke-width', 2)
              .attr('stroke-linecap', 'round')
              .attr('stroke-linejoin', 'round')
          })
        }

        // Only show text label if bar is wide enough (accounting for icon)
        const textStartX = barWidth > 30 ? startX + iconSize + iconPadding * 2 : startX
        const availableTextWidth = barWidth > 30 ? barWidth - iconSize - iconPadding * 3 : barWidth

        if (availableTextWidth > 30) {
          barGroup
            .append('text')
            .attr('class', 'bar-label')
            .attr('x', textStartX + availableTextWidth / 2)
            .attr('y', barY + barHeight / 2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('fill', 'var(--foreground)')
            .attr('font-size', '10px')
            .attr('font-weight', '500')
            .attr('pointer-events', 'none')
            .attr('data-start-time', startTime)
            .attr('data-end-time', endTime)
            .attr('data-icon-offset', barWidth > 30 ? iconSize + iconPadding * 2 : 0)
            .text(labelText.length > 10 ? labelText.slice(0, 10) + '…' : labelText)
        }

        // Duration label removed since it was barely visible - duration shown in tooltip
      })

    // Handle unpaired events (events without an end, show as small markers)
    eventPairs
      .filter((pair) => !pair.endEvent)
      .forEach((pair) => {
        const startTime = pair.startEvent.relativeTimeMs
        const x = xScale(startTime)
        const y = yScale(pair.startEvent.laneIndex) ?? 0
        const laneHeight = yScale.bandwidth()
        const markerSize = 8
        const isSelected = pair.startEvent.event_id === selectedEventId

        barsGroup
          .append('circle')
          .attr('class', 'unpaired-marker')
          .attr('cx', x)
          .attr('cy', y + laneHeight / 2)
          .attr('r', markerSize)
          .attr('fill', pair.startEvent.laneColor)
          .attr('opacity', isSelected ? 0.9 : 0.7)
          .attr('stroke', isSelected ? 'var(--ring)' : 'white')
          .attr('stroke-width', isSelected ? 2 : 1)
          .attr('cursor', 'pointer')
          .attr('data-time', startTime)
          .on('click', () => onEventClick(pair.startEvent.event_id))
          .on('mouseenter', (e: MouseEvent) => {
            const [px, py] = d3.pointer(e, containerRef.current)
            onEventHover(pair.startEvent, { x: px, y: py })
          })
          .on('mouseleave', () => onEventHover(null))
      })

    // Time axis at bottom
    const xAxis = d3
      .axisBottom(xScale)
      .ticks(tickCount)
      .tickFormat((d: d3.NumberValue) => formatDuration(d as number))

    staticGroup
      .append('g')
      .attr('transform', `translate(0,${height})`)
      .attr('class', 'timeline-axis')
      .call(xAxis)
      .selectAll('text')
      .attr('class', 'text-xs fill-muted-foreground')

    staticGroup
      .selectAll('.timeline-axis path, .timeline-axis line')
      .attr('class', 'stroke-border')

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
      .on('zoom', (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        const newXScale = event.transform.rescaleX(xScale)

        // Update axis
        staticGroup.select<SVGGElement>('.timeline-axis').call(
          xAxis.scale(newXScale) as unknown as (
            selection: d3.Selection<SVGGElement, unknown, null, undefined>
          ) => void
        )

        // Update lane backgrounds width based on zoom
        const zoomWidth = width * event.transform.k
        const translateX = event.transform.x
        laneBgGroup.selectAll<SVGRectElement, unknown>('.lane-bg').each(function (this: SVGRectElement) {
          d3.select(this)
            .attr('x', Math.min(0, translateX))
            .attr('width', Math.max(zoomWidth, width))
        })

        // Update grid lines
        gridGroup.selectAll<SVGLineElement, unknown>('.grid-line').each(function (this: SVGLineElement) {
          const line = d3.select(this)
          const time = parseFloat(line.attr('data-time') ?? '0')
          const newX = newXScale(time)
          line.attr('x1', newX).attr('x2', newX)
        })

        // Update duration bars
        barsGroup.selectAll<SVGRectElement, unknown>('.duration-bar').each(function (this: SVGRectElement) {
          const rect = d3.select(this)
          const startTime = parseFloat(rect.attr('data-start-time') ?? '0')
          const endTime = parseFloat(rect.attr('data-end-time') ?? '0')
          const newStartX = newXScale(startTime)
          const newEndX = newXScale(endTime)
          rect.attr('x', newStartX).attr('width', Math.max(newEndX - newStartX, 8))
        })

        // Update bar icons
        barsGroup.selectAll<SVGGElement, unknown>('.bar-icon').each(function (this: SVGGElement) {
          const iconGroup = d3.select(this)
          const startTime = parseFloat(iconGroup.attr('data-start-time') ?? '0')
          const newStartX = newXScale(startTime)
          const barY = parseFloat(iconGroup.attr('transform')?.match(/translate\([^,]+,\s*([^)]+)\)/)?.[1] ?? '0')
          const iconSize = 14
          const iconPadding = 4
          iconGroup.attr('transform', `translate(${newStartX + iconPadding + iconSize / 2}, ${barY})`)
        })

        // Update bar labels (accounting for icon offset)
        barsGroup.selectAll<SVGTextElement, unknown>('.bar-label').each(function (this: SVGTextElement) {
          const text = d3.select(this)
          const startTime = parseFloat(text.attr('data-start-time') ?? '0')
          const endTime = parseFloat(text.attr('data-end-time') ?? '0')
          const iconOffset = parseFloat(text.attr('data-icon-offset') ?? '0')
          const newStartX = newXScale(startTime)
          const newEndX = newXScale(endTime)
          const barWidth = newEndX - newStartX
          const textStartX = iconOffset > 0 ? newStartX + iconOffset : newStartX
          const availableWidth = iconOffset > 0 ? barWidth - iconOffset - 4 : barWidth
          text.attr('x', textStartX + availableWidth / 2)
        })

        // Update unpaired markers
        barsGroup.selectAll<SVGCircleElement, unknown>('.unpaired-marker').each(function (this: SVGCircleElement) {
          const circle = d3.select(this)
          const time = parseFloat(circle.attr('data-time') ?? '0')
          circle.attr('cx', newXScale(time))
        })

        // Update overhead bars
        overheadGroup.selectAll<SVGRectElement, unknown>('.overhead-bar').each(function (this: SVGRectElement) {
          const rect = d3.select(this)
          const startTime = parseFloat(rect.attr('data-start-time') ?? '0')
          const endTime = parseFloat(rect.attr('data-end-time') ?? '0')
          const newStartX = newXScale(startTime)
          const newEndX = newXScale(endTime)
          rect.attr('x', newStartX).attr('width', Math.max(newEndX - newStartX, 2))
        })

        // Update overhead labels
        overheadGroup.selectAll<SVGTextElement, unknown>('.overhead-label').each(function (this: SVGTextElement) {
          const text = d3.select(this)
          const startTime = parseFloat(text.attr('data-start-time') ?? '0')
          const endTime = parseFloat(text.attr('data-end-time') ?? '0')
          const newStartX = newXScale(startTime)
          const newEndX = newXScale(endTime)
          const segmentWidth = newEndX - newStartX
          text.attr('x', newStartX + segmentWidth / 2)
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
    overheadSegments,
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
