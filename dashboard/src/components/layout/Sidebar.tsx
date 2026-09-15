import { PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Section } from '../../appTypes'
import { cn } from '../../lib/utils'
import { FOOTER_ITEMS, NAV_GROUPS, type NavItem } from './nav'

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="am-logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#am-logo)" />
      <g stroke="white" strokeWidth="1.6" strokeLinecap="round" opacity="0.9">
        <line x1="10" y1="10" x2="22" y2="12" />
        <line x1="10" y1="10" x2="12" y2="22" />
        <line x1="22" y1="12" x2="12" y2="22" />
        <line x1="22" y1="12" x2="22" y2="22" />
        <line x1="12" y1="22" x2="22" y2="22" />
      </g>
      <g fill="white">
        <circle cx="10" cy="10" r="2.6" />
        <circle cx="22" cy="12" r="2.2" />
        <circle cx="12" cy="22" r="2.2" />
        <circle cx="22" cy="22" r="2.6" />
      </g>
    </svg>
  )
}

export function Sidebar({
  section,
  onSection,
  collapsed,
  onToggleCollapsed,
  badges,
  version,
  footer,
  mobileOpen,
  onMobileClose,
}: {
  section: Section
  onSection: (section: Section) => void
  collapsed: boolean
  onToggleCollapsed: () => void
  badges: Partial<Record<Section, { value: number | string; tone?: 'danger' | 'warning' | 'neutral' }>>
  version?: string
  footer?: ReactNode
  mobileOpen: boolean
  onMobileClose: () => void
}) {
  const select = (id: Section) => {
    onSection(id)
    onMobileClose()
  }
  const content = (compact: boolean) => (
    <div className="flex h-full flex-col">
      <div className={cn('flex h-14 shrink-0 items-center gap-2.5 border-b border-line', compact ? 'justify-center px-2' : 'px-4')}>
        <Logo className="size-7 shrink-0" />
        {!compact && (
          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <span className="truncate text-[14.5px] font-semibold tracking-tight text-fg">AgentMesh</span>
            {version && <span className="font-mono text-[10.5px] text-fg-subtle">v{version}</span>}
          </div>
        )}
        {mobileOpen && (
          <button aria-label="Close menu" className="grid size-7 place-items-center rounded-md text-fg-muted hover:bg-surface-2 lg:hidden" onClick={onMobileClose}>
            <X className="size-4" />
          </button>
        )}
      </div>
      <nav className={cn('flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-3', compact ? 'px-2' : 'px-2.5')} aria-label="Main">
        {NAV_GROUPS.map((group, index) => (
          <div key={group.label ?? index} className="flex flex-col gap-0.5">
            {group.label && !compact && <div className="px-2 pb-1 text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{group.label}</div>}
            {group.label && compact && <div className="mx-2 mb-1 border-t border-line" />}
            {group.items.map(item => <NavButton key={item.id} item={item} active={section === item.id} compact={compact} badge={badges[item.id]} onClick={() => select(item.id)} />)}
          </div>
        ))}
      </nav>
      <div className={cn('flex shrink-0 flex-col gap-0.5 border-t border-line py-2', compact ? 'px-2' : 'px-2.5')}>
        {FOOTER_ITEMS.map(item => <NavButton key={item.id} item={item} active={section === item.id} compact={compact} badge={badges[item.id]} onClick={() => select(item.id)} />)}
        {footer && !compact && <div className="px-2 pt-2">{footer}</div>}
        <button
          className={cn('mt-1 hidden h-8 items-center gap-2 rounded-md px-2 text-[13px] text-fg-subtle hover:bg-surface-2 hover:text-fg lg:flex', compact && 'justify-center')}
          onClick={onToggleCollapsed}
          aria-label={compact ? 'Expand sidebar' : 'Collapse sidebar'}
          title={compact ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {compact ? <PanelLeftOpen className="size-4" /> : <><PanelLeftClose className="size-4" />Collapse</>}
        </button>
      </div>
    </div>
  )
  return (
    <>
      <aside className={cn('sticky top-0 hidden h-dvh shrink-0 border-r border-line bg-surface transition-[width] duration-200 lg:block', collapsed ? 'w-14' : 'w-60')}>
        {content(collapsed)}
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={onMobileClose} />
          <aside className="animate-fade-in relative h-full w-64 border-r border-line bg-surface shadow-pop">{content(false)}</aside>
        </div>
      )}
    </>
  )
}

function NavButton({ item, active, compact, badge, onClick }: { item: NavItem; active: boolean; compact: boolean; badge?: { value: number | string; tone?: 'danger' | 'warning' | 'neutral' }; onClick: () => void }) {
  return (
    <button
      aria-current={active ? 'page' : undefined}
      title={compact ? item.label : undefined}
      className={cn(
        'group relative flex h-8 w-full items-center gap-2.5 rounded-md text-[13.5px] transition-colors [&_svg]:size-4 [&_svg]:shrink-0',
        compact ? 'justify-center px-0' : 'px-2',
        active ? 'bg-surface-2 font-medium text-fg' : 'text-fg-muted hover:bg-surface-2/70 hover:text-fg',
      )}
      onClick={onClick}
    >
      <span className={cn(active ? 'text-accent' : 'text-fg-subtle group-hover:text-fg-muted')}>{item.icon}</span>
      {!compact && <span className="flex-1 truncate text-left">{item.label}</span>}
      {badge && badge.value !== 0 && badge.value !== '' && (
        compact
          ? <span className={cn('absolute top-1 right-1 size-1.5 rounded-full', badge.tone === 'danger' ? 'bg-danger' : badge.tone === 'warning' ? 'bg-warning' : 'bg-fg-subtle')} />
          : <span className={cn('tabular rounded px-1.5 text-[11px] font-medium', badge.tone === 'danger' ? 'bg-danger-soft text-danger-text' : badge.tone === 'warning' ? 'bg-warning-soft text-warning-text' : 'bg-surface-3 text-fg-muted')}>{badge.value}</span>
      )}
    </button>
  )
}
