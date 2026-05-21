import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ListFilter } from 'lucide-react'
import { EmptyState } from '../common/Cards'
import { stringValue } from '../../utils/format'

export interface Column<T> {
  label: string
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number
  className?: string
  sticky?: 'left' | 'right'
}

export function DataTable<T>({ rows, columns, onRow, selectedRow, minWidth = 940 }: { rows: T[]; columns: Array<Column<T>>; onRow?: (row: T) => void; selectedRow?: (row: T) => boolean; minWidth?: number }) {
  const [sorting, setSorting] = useState<SortingState>([])
  const tableColumns = useMemo<Array<ColumnDef<T>>>(() => columns.map((column, index) => ({
    id: `${column.label}-${index}`,
    header: column.label,
    meta: { sticky: column.sticky },
    accessorFn: row => column.sortValue?.(row) ?? stringValue(column.render(row)),
    cell: info => <div className={column.className}>{column.render(info.row.original)}</div>,
  })), [columns])
  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })
  if (rows.length === 0)
    return <EmptyState icon={<ListFilter className="size-5" />} title="No records" />
  return (
    <div className="vision-scroll overflow-auto">
      <table className="w-full border-separate border-spacing-y-1.5 text-left" style={{ minWidth }}>
        <thead>
          {table.getHeaderGroups().map(group => (
            <tr key={group.id}>
              {group.headers.map(header => (
                <th key={header.id} className={`px-3 pb-1 text-xs/5 font-semibold text-white/58 ${stickyClass((header.column.columnDef.meta as { sticky?: unknown } | undefined)?.sticky, true)}`}>
                  <button className="inline-flex items-center gap-1 hover:text-white/85" onClick={header.column.getToggleSortingHandler()}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    <span className="text-white/35">{header.column.getIsSorted() === 'asc' ? 'up' : header.column.getIsSorted() === 'desc' ? 'down' : ''}</span>
                  </button>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map(row => (
            <tr
              key={row.id}
              className={`group rounded-2xl transition ${selectedRow?.(row.original) ? 'bg-sky-400/18 ring-1 ring-sky-200/34' : 'bg-slate-950/24 ring-1 ring-white/7'} ${onRow ? 'cursor-pointer hover:bg-sky-300/12 hover:ring-sky-200/26' : ''}`}
              onClick={() => onRow?.(row.original)}
            >
              {row.getVisibleCells().map(cell => <td key={cell.id} className={`px-3 py-2.5 text-sm/6 text-white/86 first:rounded-l-2xl last:rounded-r-2xl ${stickyClass((cell.column.columnDef.meta as { sticky?: unknown } | undefined)?.sticky, false)}`}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function stickyClass(sticky: unknown, header: boolean): string {
  if (sticky === 'right')
    return `sticky right-0 z-20 ${header ? 'bg-slate-700/95' : 'bg-slate-800/95 shadow-[-14px_0_18px_rgb(2_6_23/0.34)]'}`
  if (sticky === 'left')
    return `sticky left-0 z-20 ${header ? 'bg-slate-700/95' : 'bg-slate-800/95 shadow-[14px_0_18px_rgb(2_6_23/0.28)]'}`
  return ''
}
