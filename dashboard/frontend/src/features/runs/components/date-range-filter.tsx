/**
 * Date range filter component with presets and custom date picker.
 */

import { useCallback, useMemo, useState } from 'react'
import { format, subHours, subDays, startOfDay, endOfDay } from 'date-fns'
import { CalendarIcon, X } from 'lucide-react'
import type { DateRange } from 'react-day-picker'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'

interface DateRangeFilterProps {
  value: { from: Date | null; to: Date | null }
  onChange: (value: { from: Date | null; to: Date | null }) => void
}

type PresetValue = 'all' | '1h' | '24h' | '7d' | '30d'

const presets: { label: string; value: PresetValue }[] = [
  { label: 'All time', value: 'all' },
  { label: 'Last hour', value: '1h' },
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
]

function getPresetDates(preset: PresetValue): { from: Date | null; to: Date | null } {
  const now = new Date()

  switch (preset) {
    case 'all':
      return { from: null, to: null }
    case '1h':
      return { from: subHours(now, 1), to: now }
    case '24h':
      return { from: subHours(now, 24), to: now }
    case '7d':
      return { from: startOfDay(subDays(now, 7)), to: endOfDay(now) }
    case '30d':
      return { from: startOfDay(subDays(now, 30)), to: endOfDay(now) }
    default:
      return { from: null, to: null }
  }
}

export function DateRangeFilter({ value, onChange }: DateRangeFilterProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [showCalendar, setShowCalendar] = useState(false)
  // Local state for custom range selection (to avoid closing popover on first click)
  const [pendingRange, setPendingRange] = useState<DateRange | undefined>(undefined)
  // Track if we're waiting for the second date selection
  const [waitingForSecondDate, setWaitingForSecondDate] = useState(false)

  const hasFilter = value.from !== null || value.to !== null

  // Format display text for the button
  const displayText = useMemo(() => {
    if (!hasFilter) {
      return 'All time'
    }
    if (value.from && value.to) {
      return `${format(value.from, 'MMM d, yyyy')} - ${format(value.to, 'MMM d, yyyy')}`
    }
    if (value.from) {
      return `From ${format(value.from, 'MMM d, yyyy')}`
    }
    if (value.to) {
      return `Until ${format(value.to, 'MMM d, yyyy')}`
    }
    return 'All time'
  }, [hasFilter, value.from, value.to])

  const handlePresetClick = useCallback((preset: PresetValue) => {
    const dates = getPresetDates(preset)
    onChange(dates)
    setShowCalendar(false)
    setIsOpen(false)
  }, [onChange])

  const handleCustomClick = useCallback(() => {
    setShowCalendar(true)
    setWaitingForSecondDate(false)
    // Initialize pending range with current value
    setPendingRange(value.from || value.to ? {
      from: value.from ?? undefined,
      to: value.to ?? undefined,
    } : undefined)
  }, [value.from, value.to])

  const handleCalendarSelect = useCallback((range: DateRange | undefined) => {
    setPendingRange(range)

    if (!range?.from) {
      setWaitingForSecondDate(false)
      return
    }

    // First click - wait for second date
    if (!waitingForSecondDate) {
      setWaitingForSecondDate(true)
      return
    }

    // Second click - apply the range and close
    if (range.from && range.to) {
      onChange({
        from: range.from,
        to: range.to,
      })
      setShowCalendar(false)
      setIsOpen(false)
      setWaitingForSecondDate(false)
    }
  }, [onChange, waitingForSecondDate])

  const handleClear = useCallback(() => {
    setPendingRange(undefined)
    setShowCalendar(false)
    setIsOpen(false)
    setWaitingForSecondDate(false)
    onChange({ from: null, to: null })
  }, [onChange])

  const handleOpenChange = useCallback((open: boolean) => {
    // Don't close if we're in the middle of selecting a custom date range
    if (!open && showCalendar && waitingForSecondDate) {
      return
    }
    setIsOpen(open)
    if (!open) {
      // Reset calendar view when closing
      setShowCalendar(false)
      setPendingRange(undefined)
      setWaitingForSecondDate(false)
    }
  }, [showCalendar, waitingForSecondDate])

  return (
    <div className="flex items-center gap-2">
      <Popover open={isOpen} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            className={cn(
              'w-[280px] justify-start text-left font-normal',
              !hasFilter && 'text-muted-foreground'
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4" />
            {displayText}
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-auto p-0"
          align="start"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          onFocusOutside={(e) => e.preventDefault()}
        >
          <div className="flex">
            {/* Presets sidebar */}
            <div className="border-r p-2 space-y-1">
              {presets.map((preset) => (
                <Button
                  key={preset.value}
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => handlePresetClick(preset.value)}
                >
                  {preset.label}
                </Button>
              ))}
              <Button
                variant={showCalendar ? 'secondary' : 'ghost'}
                size="sm"
                className="w-full justify-start"
                onClick={handleCustomClick}
              >
                Custom range
              </Button>
            </div>

            {/* Calendar for custom range */}
            {showCalendar && (
              <div className="p-2">
                <Calendar
                  mode="range"
                  defaultMonth={pendingRange?.from ?? value.from ?? new Date()}
                  selected={pendingRange}
                  onSelect={handleCalendarSelect}
                  numberOfMonths={2}
                />
                <div className="flex justify-end gap-2 p-2 border-t">
                  <Button variant="ghost" size="sm" onClick={handleClear}>
                    Clear
                  </Button>
                </div>
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {hasFilter && (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleClear}
          className="h-8 px-2"
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Clear filter</span>
        </Button>
      )}
    </div>
  )
}
