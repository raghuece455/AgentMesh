import { Copy } from 'lucide-react'

export function JsonViewer({ value, compact = false, copyLabel = 'Copy JSON' }: { value: unknown; compact?: boolean; copyLabel?: string }) {
  const text = JSON.stringify(value, null, 2)
  return (
    <div className="rounded-2xl border border-white/12 bg-slate-950/38">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="text-xs/5 font-semibold text-white/56">JSON</span>
        <button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs/5 text-white/64 hover:bg-white/10 hover:text-white" onClick={() => void navigator.clipboard.writeText(text)}>
          <Copy className="size-3" />{copyLabel}
        </button>
      </div>
      <pre className={`${compact ? 'max-h-40' : 'max-h-[560px]'} vision-scroll overflow-auto whitespace-pre-wrap p-3 text-xs/5 text-white/82`}>
        {text}
      </pre>
    </div>
  )
}
