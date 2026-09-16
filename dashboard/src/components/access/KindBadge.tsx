import { Database, FileText, Globe, HardDrive, Search } from 'lucide-react'
import { Badge, type Tone } from '../ui/Badge'
import type { AccessKind } from '../../types'

/** What an agent reached: a host, an index, a memory store, a table, a file. */
export const ACCESS_KIND: Record<AccessKind, { label: string; tone: Tone; icon: typeof Globe }> = {
  network: { label: 'host', tone: 'accent', icon: Globe },
  retrieval: { label: 'index', tone: 'info', icon: Search },
  memory: { label: 'memory', tone: 'success', icon: HardDrive },
  db: { label: 'database', tone: 'violet', icon: Database },
  file: { label: 'file', tone: 'warning', icon: FileText },
  api: { label: 'api', tone: 'accent', icon: Globe },
  other: { label: 'other', tone: 'neutral', icon: FileText },
}

export function KindBadge({ kind }: { kind: AccessKind }) {
  const meta = ACCESS_KIND[kind] ?? ACCESS_KIND.other
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

export function KindIcon({ kind }: { kind: AccessKind }) {
  const Icon = (ACCESS_KIND[kind] ?? ACCESS_KIND.other).icon
  return <Icon />
}
