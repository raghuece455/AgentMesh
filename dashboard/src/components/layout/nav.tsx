import {
  BellRing,
  Bot,
  CircleDollarSign,
  ClipboardCheck,
  Code2,
  Cpu,
  Database,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  MessagesSquare,
  Plug,
  RotateCcw,
  Settings,
  ShieldCheck,
  Waypoints,
  Wrench,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Section } from '../../appTypes'

export interface NavItem {
  id: Section
  label: string
  description: string
  icon: ReactNode
}

export interface NavGroup {
  label: string | null
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { id: 'overview', label: 'Overview', description: 'Health, cost, and failures across every agent', icon: <LayoutDashboard /> },
    ],
  },
  {
    label: 'Observe',
    items: [
      { id: 'traces', label: 'Traces', description: 'Every agent run as a searchable span tree', icon: <Waypoints /> },
      { id: 'sessions', label: 'Sessions', description: 'Multi-turn conversations, turn by turn', icon: <MessagesSquare /> },
      { id: 'agents', label: 'Agents', description: 'Performance and cost per agent', icon: <Bot /> },
      { id: 'workflows', label: 'Workflows', description: 'Execution graphs for orchestrated runs', icon: <GitBranch /> },
    ],
  },
  {
    label: 'Evaluate',
    items: [
      { id: 'datasets', label: 'Datasets', description: 'Test sets, experiments, and regressions', icon: <FlaskConical /> },
      { id: 'evaluations', label: 'Evaluations', description: 'Scores from evaluators and people', icon: <ClipboardCheck /> },
      { id: 'prompts', label: 'Prompts', description: 'Prompt versions, usage, and quality', icon: <Code2 /> },
    ],
  },
  {
    label: 'Monitor',
    items: [
      { id: 'alerts', label: 'Alerts', description: 'Notify Slack or a webhook when things go wrong', icon: <BellRing /> },
      { id: 'costs', label: 'Costs', description: 'Spend, budgets, and waste', icon: <CircleDollarSign /> },
      { id: 'models', label: 'Models', description: 'Provider health and model usage', icon: <Cpu /> },
      { id: 'tools', label: 'Tools', description: 'Tool calls, risk, and failures', icon: <Wrench /> },
      { id: 'memory', label: 'Memory & RAG', description: 'Memory operations and retrievals', icon: <Database /> },
    ],
  },
  {
    label: 'Operate',
    items: [
      { id: 'approvals', label: 'Approvals', description: 'Human review for risky tool calls', icon: <ShieldCheck /> },
      { id: 'replay', label: 'Replay', description: 'Re-run a trace from recorded outputs', icon: <RotateCcw /> },
    ],
  },
]

export const FOOTER_ITEMS: NavItem[] = [
  { id: 'connect', label: 'Connect', description: 'Send traces from any framework or SDK', icon: <Plug /> },
  { id: 'settings', label: 'Settings', description: 'Budgets, providers, and audit log', icon: <Settings /> },
]

export const ALL_NAV_ITEMS: NavItem[] = [...NAV_GROUPS.flatMap(group => group.items), ...FOOTER_ITEMS]

export function navItem(section: Section): NavItem {
  return ALL_NAV_ITEMS.find(item => item.id === section) ?? ALL_NAV_ITEMS[0]
}

export function navGroupLabel(section: Section): string | null {
  return NAV_GROUPS.find(group => group.items.some(item => item.id === section))?.label ?? null
}
