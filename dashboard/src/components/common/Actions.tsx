import type { ReactNode } from 'react'

export function ActionButton({ icon, label, onClick, tone = 'neutral' }: { icon: ReactNode; label: string; onClick: () => void; tone?: 'neutral' | 'purple' | 'danger' }) {
  const toneClass = tone === 'purple'
    ? 'border-purple-200/24 bg-purple-400/16 text-purple-100 hover:bg-purple-400/24'
    : tone === 'danger'
      ? 'border-rose-200/24 bg-rose-400/16 text-rose-100 hover:bg-rose-400/24'
      : 'border-white/16 bg-black/24 text-white hover:bg-white/14'
  return (
    <button className={`inline-flex items-center justify-center gap-2 rounded-2xl border px-3 py-2 text-sm/6 font-semibold transition ${toneClass}`} onClick={onClick}>
      {icon}{label}
    </button>
  )
}

export function InlineAction({ icon, label, onClick, tone = 'neutral' }: { icon: ReactNode; label: string; onClick: () => void; tone?: 'neutral' | 'purple' | 'danger' }) {
  const toneClass = tone === 'purple'
    ? 'border-purple-200/28 bg-purple-400/18 text-purple-100 hover:bg-purple-400/28'
    : tone === 'danger'
      ? 'border-rose-200/28 bg-rose-400/18 text-rose-100 hover:bg-rose-400/28'
      : 'border-white/14 bg-slate-950/28 text-white/82 hover:bg-white/14 hover:text-white'
  return (
    <button
      className={`inline-flex items-center gap-1 rounded-xl border px-2 py-1 text-xs/5 font-semibold transition ${toneClass}`}
      onClick={event => {
        event.stopPropagation()
        onClick()
      }}
    >
      {icon}{label}
    </button>
  )
}
