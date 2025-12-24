import { useState, useEffect } from 'react'
import { useLayout } from '@/context/layout-provider'
import { ExternalLink, X } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import { AppTitle } from './app-title'
import { sidebarData } from './data/sidebar-data'
import { NavGroup } from './nav-group'

const CTA_COOKIE_NAME = 'pyworkflow_cta_dismissed'

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  return match ? match[2] : null
}

function setCookie(name: string, value: string, days: number) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString()
  document.cookie = `${name}=${value}; expires=${expires}; path=/`
}

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg
      role='img'
      viewBox='0 0 24 24'
      xmlns='http://www.w3.org/2000/svg'
      className={className}
      fill='currentColor'
    >
      <path d='M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12' />
    </svg>
  )
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg
      role='img'
      viewBox='0 0 24 24'
      xmlns='http://www.w3.org/2000/svg'
      className={className}
      fill='currentColor'
    >
      <path d='M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z' />
    </svg>
  )
}

function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns='http://www.w3.org/2000/svg'
      viewBox='0 0 24 24'
      fill='none'
      stroke='currentColor'
      strokeWidth='2'
      strokeLinecap='round'
      strokeLinejoin='round'
      className={className}
    >
      <circle cx='12' cy='12' r='10' />
      <path d='M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20' />
      <path d='M2 12h20' />
    </svg>
  )
}

function SidebarFooterContent() {
  const { state } = useSidebar()
  const isCollapsed = state === 'collapsed'
  const [showCta, setShowCta] = useState(true)

  useEffect(() => {
    const dismissed = getCookie(CTA_COOKIE_NAME)
    if (dismissed === 'true') {
      setShowCta(false)
    }
  }, [])

  const handleDismissCta = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setShowCta(false)
    setCookie(CTA_COOKIE_NAME, 'true', 30) // Hide for 30 days
  }

  return (
    <SidebarFooter className='gap-3'>
      {showCta && !isCollapsed && (
        <div className='relative overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-primary/50'>
          <button
            onClick={handleDismissCta}
            className='absolute right-1.5 top-1.5 z-10 rounded-md bg-background/80 p-1 text-muted-foreground backdrop-blur-sm transition-colors hover:bg-background hover:text-foreground'
            title='Dismiss'
          >
            <X className='h-3.5 w-3.5' />
          </button>
          <a
            href='https://flowhunt.io'
            target='_blank'
            rel='noopener noreferrer'
            className='block'
          >
            <img
              src='/images/login_signup_flow.png'
              alt='FlowHunt AI Agent Builder'
              className='h-24 w-full object-cover object-top'
            />
            <div className='p-3'>
              <div className='flex items-center justify-between'>
                <span className='text-sm font-semibold'>
                  Build AI Agents at Scale
                </span>
                <ExternalLink className='h-3.5 w-3.5 text-muted-foreground' />
              </div>
              <p className='mt-1 text-xs text-muted-foreground'>
                Made by the FlowHunt team
              </p>
            </div>
          </a>
        </div>
      )}
      <div className={`flex items-center justify-center ${isCollapsed ? 'flex-col gap-2' : 'gap-4'}`}>
        <a
          href='https://flowhunt.io'
          target='_blank'
          rel='noopener noreferrer'
          className='text-muted-foreground transition-colors hover:text-foreground'
          title='Website'
        >
          <GlobeIcon className='h-5 w-5' />
        </a>
        <a
          href='https://x.com/Yasha_br'
          target='_blank'
          rel='noopener noreferrer'
          className='text-muted-foreground transition-colors hover:text-foreground'
          title='X (Twitter)'
        >
          <XIcon className='h-4 w-4' />
        </a>
        <a
          href='https://github.com/qualityunit/pyworkflow'
          target='_blank'
          rel='noopener noreferrer'
          className='text-muted-foreground transition-colors hover:text-foreground'
          title='GitHub'
        >
          <GithubIcon className='h-5 w-5' />
        </a>
      </div>
    </SidebarFooter>
  )
}

export function AppSidebar() {
  const { collapsible, variant } = useLayout()
  return (
    <Sidebar collapsible={collapsible} variant={variant}>
      <SidebarHeader>
        <AppTitle />
      </SidebarHeader>
      <SidebarContent>
        {sidebarData.navGroups.map((props) => (
          <NavGroup key={props.title} {...props} />
        ))}
      </SidebarContent>
      <SidebarFooterContent />
      <SidebarRail />
    </Sidebar>
  )
}
