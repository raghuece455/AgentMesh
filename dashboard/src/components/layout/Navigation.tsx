import {
  Brain,
  ChevronRight,
  CircleDollarSign,
  ClipboardCheck,
  Code2,
  Database,
  GitBranch,
  LayoutDashboard,
  Moon,
  RotateCcw,
  Route,
  Settings,
  UserCheck,
  Wrench,
  Zap,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Section } from '../../appTypes'

export const navItems: Array<{ id: Section; label: string; icon: ReactNode }> = [
  { id: 'overview', label: 'Overview', icon: <LayoutDashboard className="size-4" /> },
  { id: 'traces', label: 'Traces', icon: <Route className="size-4" /> },
  { id: 'workflows', label: 'Workflows', icon: <GitBranch className="size-4" /> },
  { id: 'agents', label: 'Agents', icon: <Brain className="size-4" /> },
  { id: 'models', label: 'Models', icon: <Zap className="size-4" /> },
  { id: 'tools', label: 'Tools', icon: <Wrench className="size-4" /> },
  { id: 'memory', label: 'Memory & RAG', icon: <Database className="size-4" /> },
  { id: 'prompts', label: 'Prompts', icon: <Code2 className="size-4" /> },
  { id: 'costs', label: 'Costs', icon: <CircleDollarSign className="size-4" /> },
  { id: 'evaluations', label: 'Evaluations', icon: <ClipboardCheck className="size-4" /> },
  { id: 'approvals', label: 'Approvals', icon: <UserCheck className="size-4" /> },
  { id: 'replay', label: 'Replay', icon: <RotateCcw className="size-4" /> },
  { id: 'settings', label: 'Settings', icon: <Settings className="size-4" /> },
]

export function Sidebar({ section, onSection, onTheme }: { section: Section; onSection: (section: Section) => void; onTheme: () => void }) {
  return (
    <aside className="hidden lg:block">
      <div className="vision-glass-soft sticky top-5 border-white/22 bg-slate-950/18 p-3">
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="grid size-10 place-items-center rounded-full bg-sky-400/28 text-white ring-1 ring-sky-100/20">
            <Route className="size-5" />
          </div>
          <div>
            <div className="text-base/6 font-semibold text-white">AgentMesh</div>
            <div className="text-xs/5 text-white/55">Trace Cockpit</div>
          </div>
        </div>
        <nav className="mt-3 flex flex-col gap-1.5">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`flex items-center justify-between rounded-2xl px-3 py-2 text-sm/6 font-semibold transition ${section === item.id ? 'bg-slate-950/60 text-white ring-1 ring-white/10' : 'text-white/70 hover:bg-white/12 hover:text-white'}`}
              onClick={() => onSection(item.id)}
            >
              <span className="flex items-center gap-2">{item.icon}{item.label}</span>
              {section === item.id && <ChevronRight className="size-4" />}
            </button>
          ))}
        </nav>
        <button className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-white/14 px-3 py-2 text-sm/6 font-semibold text-white hover:bg-white/18" onClick={onTheme}>
          <Moon className="size-4" />Theme
        </button>
      </div>
    </aside>
  )
}

export function MobileNav({ section, onSection }: { section: Section; onSection: (section: Section) => void }) {
  return (
    <nav className="vision-scroll flex gap-2 overflow-auto pb-1 lg:hidden">
      {navItems.map(item => (
        <button
          key={item.id}
          className={`vision-pill inline-flex shrink-0 items-center gap-1.5 px-3 py-2 text-xs/5 ${section === item.id ? 'vision-pill-active' : ''}`}
          onClick={() => onSection(item.id)}
        >
          {item.icon}{item.label}
        </button>
      ))}
    </nav>
  )
}
