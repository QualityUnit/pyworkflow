/**
 * Refresh button with countdown timer and auto-refresh toggle.
 */

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface RefreshButtonProps {
  onRefresh: () => void
  intervalMs: number
  isFetching?: boolean
  autoRefreshEnabled?: boolean
  onAutoRefreshChange?: (enabled: boolean) => void
  className?: string
}

export function RefreshButton({
  onRefresh,
  intervalMs,
  isFetching = false,
  autoRefreshEnabled = true,
  onAutoRefreshChange,
  className,
}: RefreshButtonProps) {
  const [countdown, setCountdown] = useState(Math.floor(intervalMs / 1000))

  // Reset countdown when interval changes or after refresh
  const resetCountdown = useCallback(() => {
    setCountdown(Math.floor(intervalMs / 1000))
  }, [intervalMs])

  // Countdown timer - only run when auto-refresh is enabled
  useEffect(() => {
    if (!autoRefreshEnabled) return

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          return Math.floor(intervalMs / 1000)
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [intervalMs, autoRefreshEnabled])

  // Reset countdown when fetching starts (indicates a refresh happened)
  useEffect(() => {
    if (isFetching) {
      resetCountdown()
    }
  }, [isFetching, resetCountdown])

  // Reset countdown when auto-refresh is re-enabled
  useEffect(() => {
    if (autoRefreshEnabled) {
      resetCountdown()
    }
  }, [autoRefreshEnabled, resetCountdown])

  const handleClick = () => {
    onRefresh()
    resetCountdown()
  }

  const toggleAutoRefresh = () => {
    onAutoRefreshChange?.(!autoRefreshEnabled)
  }

  return (
    <div className={cn('flex items-center gap-1', className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClick}
            disabled={isFetching}
            className="gap-2 text-muted-foreground px-2"
          >
            <RefreshCw className={cn('h-4 w-4', isFetching && 'animate-spin')} />
            {autoRefreshEnabled ? (
              <span className="text-xs tabular-nums w-6 text-right">{countdown}s</span>
            ) : (
              <span className="text-xs text-muted-foreground">--</span>
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Click to refresh now</p>
        </TooltipContent>
      </Tooltip>

      {onAutoRefreshChange && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleAutoRefresh}
              className={cn(
                'h-8 w-8',
                autoRefreshEnabled ? 'text-muted-foreground' : 'text-amber-500'
              )}
            >
              {autoRefreshEnabled ? (
                <Pause className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{autoRefreshEnabled ? 'Pause auto-refresh' : 'Resume auto-refresh'}</p>
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  )
}
