/**
 * Date range filter component with presets and custom date picker.
 */

import { useMemo, useState } from 'react'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

interface DateRangeFilterProps {
  value: { from: Date | null; to: Date | null }
  onChange: (value: { from: Date | null; to: Date | null }) => void
}

type PresetValue = 'all' | '1h' | '24h' | '7d' | '30d' | 'custom'

const presets = [
  { label: 'All time', value: 'all' as const },
  { label: 'Last hour', value: '1h' as const },
  { label: 'Last 24 hours', value: '24h' as const },
  { label: 'Last 7 days', value: '7d' as const },
  { label: 'Last 30 days', value: '30d' as const },
  { label: 'Custom range', value: 'custom' as const },
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
    case 'custom':
      return { from: null, to: null }
    default:
      return { from: null, to: null }
  }
}

export function DateRangeFilter({ value, onChange }: DateRangeFilterProps) {
  const [selectedPreset, setSelectedPreset] = useState<PresetValue>('all')
  const [isCalendarOpen, setIsCalendarOpen] = useState(false)

  // Convert value to DateRange for calendar
  const dateRange: DateRange | undefined = useMemo(() => {
    if (!value.from && !value.to) return undefined
    return {
      from: value.from ?? undefined,
      to: value.to ?? undefined,
    }
  }, [value])

  const handlePresetChange = (preset: PresetValue) => {
    setSelectedPreset(preset)
    if (preset === 'custom') {
      setIsCalendarOpen(true)
    } else {
      onChange(getPresetDates(preset))
    }
  }

  const handleCalendarSelect = (range: DateRange | undefined) => {
    if (range) {
      onChange({
        from: range.from ?? null,
        to: range.to ?? null,
      })
    } else {
      onChange({ from: null, to: null })
    }
  }

  const handleClear = () => {
    setSelectedPreset('all')
    onChange({ from: null, to: null })
  }

  const hasFilter = value.from !== null || value.to !== null

  // Format the display text
  const displayText = useMemo(() => {
    if (!hasFilter) return null
    if (selectedPreset !== 'custom') {
      const preset = presets.find((p) => p.value === selectedPreset)
      return preset?.label ?? 'All time'
    }
    if (value.from && value.to) {
      return `${format(value.from, 'MMM d')} - ${format(value.to, 'MMM d')}`
    }
    if (value.from) {
      return `From ${format(value.from, 'MMM d')}`
    }
    if (value.to) {
      return `Until ${format(value.to, 'MMM d')}`
    }
    return null
  }, [hasFilter, selectedPreset, value])

  return (
    <div className="flex items-center gap-2">
      <Select value={selectedPreset} onValueChange={handlePresetChange}>
        <SelectTrigger className="w-[160px]">
          <CalendarIcon className="mr-2 h-4 w-4" />
          <SelectValue placeholder="Filter by date" />
        </SelectTrigger>
        <SelectContent>
          {presets.map((preset) => (
            <SelectItem key={preset.value} value={preset.value}>
              {preset.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {selectedPreset === 'custom' && (
        <Popover open={isCalendarOpen} onOpenChange={setIsCalendarOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                'justify-start text-left font-normal',
                !dateRange && 'text-muted-foreground'
              )}
            >
              <CalendarIcon className="mr-2 h-4 w-4" />
              {displayText ?? 'Pick date range'}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="range"
              defaultMonth={value.from ?? new Date()}
              selected={dateRange}
              onSelect={handleCalendarSelect}
              numberOfMonths={2}
            />
          </PopoverContent>
        </Popover>
      )}

      {hasFilter && selectedPreset !== 'custom' && (
        <span className="text-sm text-muted-foreground">{displayText}</span>
      )}

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
