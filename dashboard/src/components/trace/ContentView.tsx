import { Bot, Settings2, User, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'
import { CopyButton, JsonViewer } from '../ui/Code'
import { EmptyState } from '../ui/Card'

/** A chat message: OpenAI/Anthropic style `content`, or OpenTelemetry GenAI style `parts`. */
interface Message {
  role: string
  content?: unknown
  parts?: unknown
}

function asMessages(value: unknown): Message[] | null {
  const list = Array.isArray(value)
    ? value
    : value && typeof value === 'object' && Array.isArray((value as { messages?: unknown }).messages)
      ? (value as { messages: unknown[] }).messages
      : null
  if (!list || list.length === 0)
    return null
  const messages = list.filter((item): item is Message => Boolean(item) && typeof item === 'object' && typeof (item as Message).role === 'string' && ('content' in (item as object) || 'parts' in (item as object)))
  return messages.length === list.length ? messages : null
}

/** Split a message into readable text and any structured parts (tool calls, images) left over. */
function messageBody(message: Message): { text: string | null; rest: unknown[] } {
  const source = message.parts ?? message.content
  if (typeof source === 'string')
    return { text: source, rest: [] }
  if (!Array.isArray(source))
    return { text: null, rest: source === undefined || source === null ? [] : [source] }
  const texts: string[] = []
  const rest: unknown[] = []
  for (const part of source) {
    if (typeof part === 'string') {
      texts.push(part)
      continue
    }
    const record = (part ?? {}) as { type?: unknown; text?: unknown; content?: unknown }
    const text = typeof record.text === 'string' ? record.text : (record.type === undefined || record.type === 'text') && typeof record.content === 'string' ? record.content : null
    if (text !== null)
      texts.push(text)
    else
      rest.push(part)
  }
  return { text: texts.length ? texts.join('\n') : null, rest }
}

function partsLabel(parts: unknown[]): string {
  const types = [...new Set(parts.map(part => part && typeof part === 'object' ? String((part as { type?: unknown }).type ?? 'data') : 'data'))]
  return types.join(', ').replaceAll('_', ' ')
}

const ROLE_STYLE: Record<string, { icon: ReactNode; label: string; className: string }> = {
  system: { icon: <Settings2 />, label: 'System', className: 'bg-surface-2' },
  user: { icon: <User />, label: 'User', className: 'bg-surface' },
  assistant: { icon: <Bot />, label: 'Assistant', className: 'bg-accent-soft/50' },
  tool: { icon: <Wrench />, label: 'Tool', className: 'bg-warning-soft/60' },
}

/**
 * Renders captured input or output the way a person reads it: chat messages as a
 * conversation, plain strings as text, anything else as highlighted JSON.
 */
export function ContentView({ value, emptyTitle = 'Nothing captured', label = 'JSON' }: { value: unknown; emptyTitle?: string; label?: string }) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0) || (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0))
    return <EmptyState className="py-8" title={emptyTitle} detail="Enable content capture in the SDK or exporter to record prompts and responses." />
  if (typeof value === 'string') {
    return (
      <div className="group relative rounded-lg border border-line bg-surface-2/60">
        <CopyButton text={value} className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100" />
        <div className="max-h-[480px] overflow-auto p-3 text-[13px] leading-6 whitespace-pre-wrap break-words text-fg">{value}</div>
      </div>
    )
  }
  const messages = asMessages(value)
  if (messages) {
    return (
      <div className="flex flex-col gap-2">
        {messages.map((message, index) => {
          const style = ROLE_STYLE[message.role] ?? { icon: <Bot />, label: message.role, className: 'bg-surface' }
          const { text, rest } = messageBody(message)
          return (
            <div key={index} className={cn('rounded-lg border border-line', style.className)}>
              <div className="flex items-center justify-between gap-2 border-b border-line/70 px-3 py-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-fg-muted [&_svg]:size-3.5">{style.icon}{style.label}</span>
                {text && <CopyButton text={text} />}
              </div>
              {text !== null && <div className="max-h-80 overflow-auto px-3 py-2 text-[13px] leading-6 whitespace-pre-wrap break-words text-fg">{text}</div>}
              {rest.length > 0 && <div className="p-2"><JsonViewer value={rest.length === 1 ? rest[0] : rest} label={partsLabel(rest)} maxHeight="max-h-72" /></div>}
            </div>
          )
        })}
      </div>
    )
  }
  return <JsonViewer value={value} label={label} />
}
