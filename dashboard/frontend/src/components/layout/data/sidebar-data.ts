import {
  LayoutDashboard,
  Play,
  Workflow,
  Settings,
  BookOpen,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'Monitoring',
      items: [
        {
          title: 'Dashboard',
          url: '/',
          icon: LayoutDashboard,
        },
        {
          title: 'Workflow Runs',
          url: '/runs',
          icon: Play,
        },
        {
          title: 'My Workflows',
          url: '/workflows',
          icon: Workflow,
        },
      ],
    },
    {
      title: 'System',
      items: [
        {
          title: 'Settings',
          url: '/settings',
          icon: Settings,
        },
        {
          title: 'Documentation',
          url: 'https://docs.pyworkflow.dev',
          icon: BookOpen,
        },
      ],
    },
  ],
}
