import { X } from 'lucide-react'
import { useEffect } from 'react'
import { Button, Kbd } from '../ui/Button'

const GROUPS: Array<{ title: string; items: Array<{ keys: string[]; label: string }> }> = [
  {
    title: 'Anywhere',
    items: [
      { keys: ['Ctrl', 'K'], label: 'Search pages, traces, and sessions' },
      { keys: ['/'], label: 'Open search' },
      { keys: ['?'], label: 'Show keyboard shortcuts' },
    ],
  },
  {
    title: 'Go to',
    items: [
      { keys: ['g', 'o'], label: 'Overview' },
      { keys: ['g', 't'], label: 'Traces' },
      { keys: ['g', 's'], label: 'Sessions' },
      { keys: ['g', 'd'], label: 'Datasets' },
      { keys: ['g', 'e'], label: 'Evaluations' },
      { keys: ['g', 'a'], label: 'Alerts' },
      { keys: ['g', 'c'], label: 'Costs' },
      { keys: ['g', 'm'], label: 'Models' },
      { keys: ['g', 'w'], label: 'Workflows' },
    ],
  },
  {
    title: 'Trace view',
    items: [
      { keys: ['j'], label: 'Next span' },
      { keys: ['k'], label: 'Previous span' },
      { keys: [']'], label: 'Next trace' },
      { keys: ['['], label: 'Previous trace' },
      { keys: ['c'], label: 'Compare with another trace' },
      { keys: ['Esc'], label: 'Back to all traces' },
    ],
  },
]

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open)
      return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' || event.key === '?')
        onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open)
    return null
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[10vh]">
      <button aria-label="Close shortcuts" className="animate-fade-in absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" className="animate-fade-in relative w-full max-w-2xl overflow-hidden rounded-xl border border-line bg-surface shadow-pop">
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-[15px] font-semibold text-fg">Keyboard shortcuts</h2>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}><X /></Button>
        </header>
        <div className="grid max-h-[70vh] grid-cols-1 gap-6 overflow-y-auto p-5 sm:grid-cols-2">
          {GROUPS.map(group => (
            <section key={group.title} className={group.title === 'Go to' ? 'sm:row-span-2' : undefined}>
              <h3 className="mb-2 text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{group.title}</h3>
              <ul className="flex flex-col gap-1.5">
                {group.items.map(item => (
                  <li key={item.label} className="flex items-center justify-between gap-4 text-[13px]">
                    <span className="text-fg-muted">{item.label}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      {item.keys.map((key, index) => (
                        <span key={index} className="flex items-center gap-1">
                          {index > 0 && item.keys[0] === 'g' && <span className="text-[11px] text-fg-subtle">then</span>}
                          <Kbd>{key}</Kbd>
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
