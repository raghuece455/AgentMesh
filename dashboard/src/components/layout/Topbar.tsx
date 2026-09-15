import { ChevronRight, Menu as MenuIcon, Monitor, Moon, RefreshCw, Search, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { LiveStatus, Section } from '../../appTypes'
import { cn } from '../../lib/utils'
import { formatRelative } from '../../utils/format'
import { TIME_RANGES, type TimeRange } from '../../utils/traces'
import { Button, Kbd } from '../ui/Button'
import { Select } from '../ui/Field'
import { Menu } from '../ui/Overlay'
import { Segmented } from '../ui/Tabs'
import { navGroupLabel, navItem } from './nav'

export type ThemeSetting = 'system' | 'light' | 'dark'
export type DataScope = 'all' | 'real' | 'demo'

export function Topbar({
  section,
  crumb,
  onCrumbRoot,
  onOpenCommand,
  range,
  onRange,
  scope,
  onScope,
  liveStatus,
  lastUpdated,
  loading,
  onRefresh,
  theme,
  onTheme,
  onMobileMenu,
}: {
  section: Section
  crumb?: string
  onCrumbRoot?: () => void
  onOpenCommand: () => void
  range: TimeRange
  onRange: (range: TimeRange) => void
  scope: DataScope
  onScope: (scope: DataScope) => void
  liveStatus: LiveStatus
  lastUpdated: string | null
  loading: boolean
  onRefresh: () => void
  theme: ThemeSetting
  onTheme: (theme: ThemeSetting) => void
  onMobileMenu: () => void
}) {
  const item = navItem(section)
  const group = navGroupLabel(section)
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => tick(value => value + 1), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur-md">
      <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
        <Button variant="ghost" size="icon-sm" className="lg:hidden" aria-label="Open menu" onClick={onMobileMenu}><MenuIcon /></Button>
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13.5px]">
          {group && <span className="hidden text-fg-subtle sm:inline">{group}</span>}
          {group && <ChevronRight className="hidden size-3.5 text-fg-subtle sm:inline" />}
          {crumb
            ? (
                <>
                  <button className="truncate text-fg-muted hover:text-fg" onClick={onCrumbRoot}>{item.label}</button>
                  <ChevronRight className="size-3.5 shrink-0 text-fg-subtle" />
                  <span className="truncate font-medium text-fg">{crumb}</span>
                </>
              )
            : <span className="truncate font-medium text-fg">{item.label}</span>}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <button
            className="hidden h-8 w-56 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg-subtle shadow-card transition-colors hover:border-line-strong hover:text-fg-muted md:flex xl:w-72"
            onClick={onOpenCommand}
          >
            <Search className="size-3.5" />
            <span className="flex-1 text-left">Search or jump to...</span>
            <Kbd>Ctrl K</Kbd>
          </button>
          <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Search" onClick={onOpenCommand}><Search /></Button>
          <Select aria-label="Data scope" className="hidden w-28 sm:inline-flex" value={scope} onChange={event => onScope(event.target.value as DataScope)}>
            <option value="all">All data</option>
            <option value="real">Real runs</option>
            <option value="demo">Demo only</option>
          </Select>
          <Segmented
            className="hidden sm:inline-flex"
            value={range}
            onChange={onRange}
            options={TIME_RANGES.map(option => ({ value: option.value, label: option.label, title: option.title }))}
          />
          <div className="hidden h-8 items-center gap-2 px-1 text-xs text-fg-subtle xl:flex" title={liveStatus === 'connected' ? 'Receiving live trace events' : `Live stream ${liveStatus}`}>
            <span className="relative inline-flex size-2">
              {liveStatus === 'connected' && <span className="animate-live absolute inset-0 rounded-full bg-success opacity-60" />}
              <span className={cn('relative size-2 rounded-full', liveStatus === 'connected' ? 'bg-success' : liveStatus === 'connecting' ? 'bg-warning' : 'bg-danger')} />
            </span>
            <span>{liveStatus === 'connected' ? 'Live' : liveStatus === 'connecting' ? 'Connecting' : 'Offline'}</span>
            {lastUpdated && <span className="text-fg-subtle/80">· {formatRelative(lastUpdated)}</span>}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh" title="Refresh" onClick={onRefresh}>
            <RefreshCw className={cn(loading && 'animate-spin')} />
          </Button>
          <Menu
            trigger={({ toggle }) => (
              <Button variant="ghost" size="icon-sm" aria-label="Theme" title="Theme" onClick={toggle}>
                {theme === 'dark' ? <Moon /> : theme === 'light' ? <Sun /> : <Monitor />}
              </Button>
            )}
            items={[
              { label: 'Light', icon: <Sun />, onSelect: () => onTheme('light'), hint: theme === 'light' ? 'on' : undefined },
              { label: 'Dark', icon: <Moon />, onSelect: () => onTheme('dark'), hint: theme === 'dark' ? 'on' : undefined },
              { label: 'System', icon: <Monitor />, onSelect: () => onTheme('system'), hint: theme === 'system' ? 'on' : undefined },
            ]}
          />
        </div>
      </div>
      <div className="flex items-center gap-2 border-t border-line px-4 py-2 sm:hidden">
        <Segmented size="sm" value={range} onChange={onRange} options={TIME_RANGES.map(option => ({ value: option.value, label: option.label, title: option.title }))} />
        <Select aria-label="Data scope" className="ml-auto w-28" value={scope} onChange={event => onScope(event.target.value as DataScope)}>
          <option value="all">All data</option>
          <option value="real">Real runs</option>
          <option value="demo">Demo only</option>
        </Select>
      </div>
    </header>
  )
}
