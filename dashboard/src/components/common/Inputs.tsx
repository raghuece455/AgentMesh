import type { JsonRecord } from '../../types'
import { stringValue } from '../../utils/format'

export function FilterField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-xs/5 font-medium text-white/56">{label}</span>
      <input className="mt-1 h-9 w-full rounded-2xl border border-white/14 bg-slate-950/32 px-3 text-sm/6 text-white outline-hidden placeholder:text-white/35 focus:border-sky-200/50" value={value} onChange={event => onChange(event.target.value)} />
    </label>
  )
}

export function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="text-xs/5 font-medium text-white/56">{label}</span>
      <select className="mt-1 h-9 w-full rounded-2xl border border-white/14 bg-slate-950/36 px-3 text-sm/6 font-medium text-white outline-hidden focus:border-sky-200/50" value={value} onChange={event => onChange(event.target.value)}>
        {options.map(([option, labelText]) => <option key={option} value={option}>{labelText}</option>)}
      </select>
    </label>
  )
}

export function getFilterValue(filters: JsonRecord, key: string): string {
  return stringValue(filters[key])
}
