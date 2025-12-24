import { useState, type JSX } from 'react'
import { useLocation, useNavigate, Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type SidebarNavProps = React.HTMLAttributes<HTMLElement> & {
  items: {
    href: string
    title: string
    icon: JSX.Element
    disabled?: boolean
    badge?: string
  }[]
}

export function SidebarNav({ className, items, ...props }: SidebarNavProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [val, setVal] = useState(pathname ?? '/settings')

  const handleSelect = (e: string) => {
    setVal(e)
    navigate({ to: e })
  }

  return (
    <>
      <div className='p-1 md:hidden'>
        <Select value={val} onValueChange={handleSelect}>
          <SelectTrigger className='h-12 sm:w-48'>
            <SelectValue placeholder='Theme' />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.href} value={item.href}>
                <div className='flex gap-x-4 px-2 py-1'>
                  <span className='scale-125'>{item.icon}</span>
                  <span className='text-md'>{item.title}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <nav
        className={cn(
          'hidden w-full min-w-40 flex-col space-y-1 bg-background px-1 py-2 md:flex',
          className
        )}
        {...props}
      >
        {items.map((item) =>
          item.disabled ? (
            <span
              key={item.href}
              className={cn(
                buttonVariants({ variant: 'ghost' }),
                'justify-start opacity-50 cursor-not-allowed'
              )}
            >
              <span className='me-2'>{item.icon}</span>
              {item.title}
              {item.badge && (
                <Badge variant='secondary' className='ms-auto text-xs'>
                  {item.badge}
                </Badge>
              )}
            </span>
          ) : (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                buttonVariants({ variant: 'ghost' }),
                pathname === item.href
                  ? 'bg-muted hover:bg-accent'
                  : 'hover:bg-accent hover:underline',
                'justify-start'
              )}
            >
              <span className='me-2'>{item.icon}</span>
              {item.title}
              {item.badge && (
                <Badge variant='secondary' className='ms-auto text-xs'>
                  {item.badge}
                </Badge>
              )}
            </Link>
          )
        )}
      </nav>
    </>
  )
}
