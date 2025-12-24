import { Link } from '@tanstack/react-router'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'

function PyWorkflowLogo({ className }: { className?: string }) {
  return (
    <svg
      xmlns='http://www.w3.org/2000/svg'
      viewBox='0 0 16 16'
      fill='none'
      className={className}
    >
      <path
        fillRule='evenodd'
        clipRule='evenodd'
        fill='currentColor'
        d='M13.6 5.5998C14.9255 5.5998 16 4.52529 16 3.1998C16 1.87432 14.9255 0.799805 13.6 0.799805C12.5373 0.799805 11.6359 1.49055 11.3203 2.44757C8.9912 2.77772 7.2 4.77958 7.2 7.1998V8.7998C7.2 10.348 6.10053 11.6394 4.63979 11.9358C4.29294 11.0372 3.42091 10.3998 2.4 10.3998C1.07452 10.3998 0 11.4743 0 12.7998C0 14.1253 1.07452 15.1998 2.4 15.1998C3.46274 15.1998 4.36414 14.5091 4.67975 13.552C7.0088 13.2219 8.8 11.22 8.8 8.7998V7.1998C8.8 5.6516 9.89947 4.36019 11.3602 4.06378C11.7071 4.96236 12.5791 5.5998 13.6 5.5998ZM13.6 3.9998C14.0418 3.9998 14.4 3.64163 14.4 3.1998C14.4 2.75798 14.0418 2.3998 13.6 2.3998C13.1582 2.3998 12.8 2.75798 12.8 3.1998C12.8 3.64163 13.1582 3.9998 13.6 3.9998ZM2.4 13.5998C2.84183 13.5998 3.2 13.2416 3.2 12.7998C3.2 12.358 2.84183 11.9998 2.4 11.9998C1.95817 11.9998 1.6 12.358 1.6 12.7998C1.6 13.2416 1.95817 13.5998 2.4 13.5998Z'
      />
    </svg>
  )
}

export function AppTitle() {
  const { setOpenMobile } = useSidebar()
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          size='lg'
          className='gap-2 py-0 hover:bg-transparent active:bg-transparent'
          asChild
        >
          <Link
            to='/'
            onClick={() => setOpenMobile(false)}
            className='flex items-center gap-2'
          >
            <div className='flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground'>
              <PyWorkflowLogo className='size-5' />
            </div>
            <div className='grid flex-1 text-start text-sm leading-tight'>
              <span className='truncate font-bold'>PyWorkflow</span>
              <span className='truncate text-xs text-muted-foreground'>
                Dashboard
              </span>
            </div>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
