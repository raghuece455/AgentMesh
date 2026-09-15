import { Check, Copy } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { cn } from '../../lib/utils'
import { shortId } from '../../utils/format'

export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false)
  return [copied, (text: string) => {
    void navigator.clipboard?.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }]
}

export function CopyButton({ text, label, className }: { text: string; label?: string; className?: string }) {
  const [copied, copy] = useCopy()
  return (
    <button
      className={cn('inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-xs text-fg-subtle transition-colors hover:bg-surface-2 hover:text-fg [&_svg]:size-3', className)}
      onClick={event => {
        event.stopPropagation()
        copy(text)
      }}
      aria-label={label ?? 'Copy'}
    >
      {copied ? <Check className="text-success" /> : <Copy />}
      {label && <span>{copied ? 'Copied' : label}</span>}
    </button>
  )
}

/** Monospace id with a copy action, shortened unless `full`. */
export function CopyableId({ value, full = false, className }: { value: string | null | undefined; full?: boolean; className?: string }) {
  const [copied, copy] = useCopy()
  const text = value ?? ''
  if (!text)
    return <span className="text-fg-subtle">-</span>
  return (
    <button
      title={copied ? 'Copied' : `Copy ${text}`}
      className={cn('group inline-flex max-w-full items-center gap-1 rounded px-1 -mx-1 font-mono text-xs text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg', className)}
      onClick={event => {
        event.stopPropagation()
        copy(text)
      }}
    >
      <span className="truncate">{full ? text : shortId(text)}</span>
      {copied ? <Check className="size-3 shrink-0 text-success" /> : <Copy className="size-3 shrink-0 opacity-0 group-hover:opacity-100" />}
    </button>
  )
}

export function CodeBlock({ code, language, className, maxHeight = 'max-h-96' }: { code: string; language?: string; className?: string; maxHeight?: string }) {
  return (
    <div className={cn('group relative overflow-hidden rounded-lg border border-line bg-surface-2', className)}>
      <div className="flex h-8 items-center justify-between border-b border-line px-3">
        <span className="font-mono text-[11px] text-fg-subtle">{language ?? ''}</span>
        <CopyButton text={code} label="Copy" />
      </div>
      <pre className={cn('overflow-auto p-3 font-mono text-xs leading-5 text-fg', maxHeight)}><code>{code}</code></pre>
    </div>
  )
}

/** Code samples for several languages behind one set of tabs. */
export function CodeTabs({ samples }: { samples: Array<{ label: string; language: string; code: string }> }) {
  const [active, setActive] = useState(0)
  const sample = samples[active] ?? samples[0]
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex items-center justify-between gap-2 border-b border-line pr-2">
        <div className="flex min-w-0 overflow-x-auto">
          {samples.map((item, index) => (
            <button
              key={item.label}
              className={cn('-mb-px h-9 shrink-0 border-b-2 px-3 text-[12.5px] font-medium', index === active ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg')}
              onClick={() => setActive(index)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <CopyButton text={sample.code} label="Copy" />
      </div>
      <pre className="max-h-96 overflow-auto p-3 font-mono text-xs leading-5 text-fg"><code>{sample.code}</code></pre>
    </div>
  )
}

const TOKEN = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g

function highlight(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    if (index > last)
      parts.push(text.slice(last, index))
    const token = match[0]
    const kind = token.startsWith('"') ? (match[2] ? 'json-key' : 'json-string') : /true|false|null/.test(token) ? 'json-literal' : 'json-number'
    parts.push(<span key={index} className={kind}>{token}</span>)
    last = index + token.length
  }
  if (last < text.length)
    parts.push(text.slice(last))
  return parts
}

export function JsonViewer({ value, className, maxHeight = 'max-h-[520px]', label = 'JSON' }: { value: unknown; className?: string; maxHeight?: string; label?: string }) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2) ?? String(value)
    }
    catch {
      return String(value)
    }
  }, [value])
  const nodes = useMemo(() => text.length > 200_000 ? [text] : highlight(text), [text])
  return (
    <div className={cn('overflow-hidden rounded-lg border border-line bg-surface-2', className)}>
      <div className="flex h-8 items-center justify-between border-b border-line px-3">
        <span className="text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{label}</span>
        <CopyButton text={text} label="Copy" />
      </div>
      <pre className={cn('overflow-auto p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words text-fg', maxHeight)}>{nodes}</pre>
    </div>
  )
}
