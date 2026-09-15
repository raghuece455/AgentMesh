import { Database, Plus, X } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { addTraceToDataset, createDataset, listDatasets } from '../../api'
import type { DatasetSummary } from '../../types'
import { errorText } from '../../utils/format'

/** Turn a trace into a regression test: copy its input (and, optionally, its output as the expected answer) into a dataset. */
export function AddToDataset({ traceId }: { traceId: string }) {
  const [open, setOpen] = useState(false)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [name, setName] = useState('')
  const [useOutput, setUseOutput] = useState(true)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open)
      return
    listDatasets().then(items => {
      setDatasets(items)
      setName(current => current || items[0]?.name || '')
    }).catch(() => setDatasets([]))
  }, [open])

  useEffect(() => {
    setMessage('')
  }, [traceId])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const target = name.trim()
    if (!target)
      return
    setBusy(true)
    try {
      if (!datasets.some(dataset => dataset.name === target))
        await createDataset({ name: target })
      await addTraceToDataset(target, { trace_id: traceId, use_trace_output: useOutput })
      setMessage(`Added to ${target}`)
      setOpen(false)
    }
    catch (caught) {
      setMessage(errorText(caught))
    }
    finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <span className="inline-flex items-center gap-2">
        <button className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/16 bg-black/24 px-3 py-2 text-sm/6 font-semibold text-white transition hover:bg-white/14" onClick={() => setOpen(true)}>
          <Database className="size-4" />Add to dataset
        </button>
        {message && <span className="text-xs/5 text-emerald-100">{message}</span>}
      </span>
    )
  }
  return (
    <form className="flex flex-wrap items-center gap-2 rounded-2xl border border-sky-200/24 bg-sky-400/10 p-2" onSubmit={event => void submit(event)}>
      <input
        list={`datasets-${traceId}`}
        aria-label="Dataset name"
        className="h-9 w-48 rounded-xl border border-white/16 bg-slate-950/40 px-3 text-sm/6 text-white [color-scheme:dark] placeholder:text-white/40"
        placeholder="dataset name"
        value={name}
        onChange={event => setName(event.target.value)}
      />
      <datalist id={`datasets-${traceId}`}>
        {datasets.map(dataset => <option key={dataset.dataset_id} value={dataset.name} />)}
      </datalist>
      <label className="flex items-center gap-1.5 text-xs/5 text-white/78">
        <input type="checkbox" checked={useOutput} onChange={event => setUseOutput(event.target.checked)} />
        Recorded output is the expected answer
      </label>
      <button type="submit" className="trace-action" disabled={busy || !name.trim()}><Plus className="size-4" />Add</button>
      <button type="button" className="trace-action" aria-label="Cancel" onClick={() => setOpen(false)}><X className="size-4" /></button>
      {message && <span className="basis-full text-xs/5 text-rose-100">{message}</span>}
    </form>
  )
}
