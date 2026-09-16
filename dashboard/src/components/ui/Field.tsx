import { ChevronDown, Search, X } from 'lucide-react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

const control = 'w-full min-w-0 rounded-lg border border-line bg-surface text-[13px] text-fg shadow-card transition-colors placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:opacity-60'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input autoComplete="off" className={cn(control, 'h-8 px-2.5', className)} {...props} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(control, 'min-h-20 px-2.5 py-2 font-mono text-xs leading-5', className)} {...props} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={cn('relative inline-flex min-w-0', className)}>
      <select className={cn(control, 'h-8 appearance-none pr-7 pl-2.5')} {...props}>{children}</select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 text-fg-subtle" />
    </span>
  )
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <span className="text-xs font-medium text-fg-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-fg-subtle">{hint}</span>}
    </label>
  )
}

export function TextField({ label, value, onChange, placeholder, type = 'text', hint, className }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; hint?: ReactNode; className?: string }) {
  return (
    <Field label={label} hint={hint} className={className}>
      <Input type={type} value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} />
    </Field>
  )
}

export function SelectField({ label, value, options, onChange, hint, className, groups }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void; hint?: ReactNode; className?: string; groups?: Record<string, string> }) {
  return (
    <Field label={label} hint={hint} className={className}>
      <Select className="w-full" value={value} onChange={event => onChange(event.target.value)}>
        {groups
          ? groupOptions(options, groups).map(([name, items]) => (
              <optgroup key={name} label={name}>
                {items.map(([option, text]) => <option key={option} value={option}>{text}</option>)}
              </optgroup>
            ))
          : options.map(([option, text]) => <option key={option} value={option}>{text}</option>)}
      </Select>
    </Field>
  )
}

/** Options in the order given, split wherever the group name changes. */
function groupOptions(options: Array<[string, string]>, groups: Record<string, string>): Array<[string, Array<[string, string]>]> {
  const sections: Array<[string, Array<[string, string]>]> = []
  for (const option of options) {
    const name = groups[option[0]] ?? ''
    const last = sections[sections.length - 1]
    if (last && last[0] === name)
      last[1].push(option)
    else
      sections.push([name, [option]])
  }
  return sections
}

export function SearchInput({ value, onChange, placeholder = 'Search', className, onSubmit }: { value: string; onChange: (value: string) => void; placeholder?: string; className?: string; onSubmit?: () => void }) {
  return (
    <span className={cn('relative inline-flex min-w-0 items-center', className)}>
      <Search className="pointer-events-none absolute left-2.5 size-3.5 text-fg-subtle" />
      <Input
        className="pr-7 pl-8"
        value={value}
        placeholder={placeholder}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter')
            onSubmit?.()
        }}
      />
      {value && (
        <button aria-label="Clear search" className="absolute right-1.5 grid size-5 place-items-center rounded text-fg-subtle hover:bg-surface-2 hover:text-fg" onClick={() => onChange('')}>
          <X className="size-3" />
        </button>
      )}
    </span>
  )
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label?: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-fg-muted">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        className={cn('relative inline-flex h-4.5 w-8 shrink-0 items-center rounded-full transition-colors', checked ? 'bg-accent' : 'bg-surface-3')}
        onClick={() => onChange(!checked)}
      >
        <span className={cn('inline-block size-3.5 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-4' : 'translate-x-0.5')} />
      </button>
      {label && <span>{label}</span>}
    </label>
  )
}
