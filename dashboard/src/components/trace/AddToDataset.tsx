import { DatabaseZap, Plus } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { addTraceToDataset, createDataset, listDatasets } from '../../api'
import type { DatasetSummary } from '../../types'
import { errorText } from '../../utils/format'
import { Button } from '../ui/Button'
import { Field, Input, Switch } from '../ui/Field'
import { Drawer } from '../ui/Overlay'

/** Turn a trace into a regression test: copy its input (and, optionally, its output as the expected answer) into a dataset. */
export function AddToDataset({ traceId, onDone }: { traceId: string; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [name, setName] = useState('')
  const [useOutput, setUseOutput] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open)
      return
    setError('')
    listDatasets().then(items => {
      setDatasets(items)
      setName(current => current || items[0]?.name || '')
    }).catch(() => setDatasets([]))
  }, [open])

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    const target = name.trim()
    if (!target)
      return
    setBusy(true)
    try {
      if (!datasets.some(dataset => dataset.name === target))
        await createDataset({ name: target })
      await addTraceToDataset(target, { trace_id: traceId, use_trace_output: useOutput })
      setOpen(false)
      onDone(`Added this trace to ${target}.`)
    }
    catch (caught) {
      setError(errorText(caught))
    }
    finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button icon={<DatabaseZap />} onClick={() => setOpen(true)}>Add to dataset</Button>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Add trace to dataset"
        description="Save this run as a test case so future experiments can check it."
        footer={(
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" icon={<Plus />} disabled={busy || !name.trim()} onClick={() => void submit()}>Add to dataset</Button>
          </>
        )}
      >
        <form className="flex flex-col gap-4" onSubmit={event => void submit(event)}>
          <Field label="Dataset" hint="Pick an existing dataset or type a new name to create one.">
            <Input list={`datasets-${traceId}`} placeholder="support-regressions" value={name} onChange={event => setName(event.target.value)} autoFocus />
            <datalist id={`datasets-${traceId}`}>
              {datasets.map(dataset => <option key={dataset.dataset_id} value={dataset.name} />)}
            </datalist>
          </Field>
          {datasets.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {datasets.slice(0, 8).map(dataset => (
                <button type="button" key={dataset.dataset_id} className={`h-7 rounded-md border px-2 text-xs ${dataset.name === name ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'}`} onClick={() => setName(dataset.name)}>
                  {dataset.name} <span className="text-fg-subtle">{dataset.item_count}</span>
                </button>
              ))}
            </div>
          )}
          <div className="rounded-lg border border-line p-3">
            <Switch checked={useOutput} onChange={setUseOutput} label="Use the recorded output as the expected answer" />
            <p className="mt-1.5 pl-10 text-xs text-fg-subtle">Turn this off to save only the input, for example when this run's answer was wrong.</p>
          </div>
          {error && <p className="text-[13px] text-danger-text">{error}</p>}
        </form>
      </Drawer>
    </>
  )
}
