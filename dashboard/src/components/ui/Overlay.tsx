import { X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/utils'
import { Button } from './Button'

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open)
      return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape')
        onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
}

/**
 * Right-hand slide-over panel, used for create forms and record details. Rendered in a portal:
 * an animated (transformed) ancestor would otherwise become the containing block for `fixed`.
 */
export function Drawer({ open, onClose, title, description, children, footer, width = 'max-w-lg' }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; width?: string }) {
  useEscape(open, onClose)
  if (!open)
    return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close panel" className="absolute inset-0 bg-black/30 backdrop-blur-[1px] animate-fade-in" onClick={onClose} />
      <aside role="dialog" aria-modal="true" className={cn('animate-slide-in relative flex h-full w-full flex-col border-l border-line bg-surface shadow-pop', width)}>
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-fg">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}><X /></Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  )
}

/**
 * Small dropdown menu anchored to a trigger button. Rendered in a portal so table and card
 * overflow never clips it.
 */
export function Menu({ trigger, items, align = 'right' }: { trigger: (props: { open: boolean; toggle: () => void }) => ReactNode; items: Array<{ label: ReactNode; icon?: ReactNode; onSelect: () => void; danger?: boolean; hint?: ReactNode }>; align?: 'left' | 'right' }) {
  const [position, setPosition] = useState<{ top: number; left?: number; right?: number } | null>(null)
  const anchorRef = useRef<HTMLSpanElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const open = position !== null
  const close = useCallback(() => setPosition(null), [])
  useEscape(open, close)
  useEffect(() => {
    if (!open)
      return
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (!anchorRef.current?.contains(target) && !menuRef.current?.contains(target))
        close()
    }
    window.addEventListener('pointerdown', onPointer)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [open, close])
  const toggle = () => {
    if (open) {
      close()
      return
    }
    const rect = anchorRef.current?.getBoundingClientRect()
    if (!rect)
      return
    setPosition(align === 'right' ? { top: rect.bottom + 4, right: window.innerWidth - rect.right } : { top: rect.bottom + 4, left: rect.left })
  }
  return (
    <span ref={anchorRef} className="relative inline-flex">
      {trigger({ open, toggle })}
      {position && createPortal(
        <div ref={menuRef} role="menu" style={{ top: position.top, left: position.left, right: position.right }} className="animate-fade-in fixed z-[80] min-w-48 overflow-hidden rounded-lg border border-line bg-surface p-1 shadow-pop">
          {items.map((item, index) => (
            <button
              key={index}
              role="menuitem"
              className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] [&_svg]:size-3.5', item.danger ? 'text-danger-text hover:bg-danger-soft' : 'text-fg hover:bg-surface-2')}
              onClick={() => {
                close()
                item.onSelect()
              }}
            >
              {item.icon && <span className="text-fg-subtle">{item.icon}</span>}
              <span className="flex-1">{item.label}</span>
              {item.hint && <span className="text-xs text-fg-subtle">{item.hint}</span>}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </span>
  )
}

/** Temporary confirmation message, shown in the bottom right corner. */
export function Toast({ message, tone = 'neutral', onDone }: { message: string; tone?: 'neutral' | 'danger' | 'success'; onDone: () => void }) {
  useEffect(() => {
    if (!message)
      return
    const timer = window.setTimeout(onDone, 3200)
    return () => window.clearTimeout(timer)
  }, [message, onDone])
  if (!message)
    return null
  return createPortal(
    <div role="status" className={cn('animate-fade-in fixed right-4 bottom-4 z-[60] max-w-sm rounded-lg border px-3.5 py-2.5 text-[13px] shadow-pop', tone === 'danger' ? 'border-danger/30 bg-danger-soft text-danger-text' : tone === 'success' ? 'border-success/30 bg-surface text-fg' : 'border-line bg-surface text-fg')}>
      {message}
    </div>,
    document.body,
  )
}
