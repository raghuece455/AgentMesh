import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { cn } from '../../lib/utils'
import { EmptyState } from './Card'

export interface Column<T> {
  label: ReactNode
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number
  align?: 'left' | 'right' | 'center'
  className?: string
  /** CSS width, e.g. '120px' or '30%'. */
  width?: string
}

interface ColumnMeta {
  align?: 'left' | 'right' | 'center'
  className?: string
  width?: string
}

/**
 * Dense, sortable table in the style of Linear and Datadog lists: hairline rows, sticky
 * header, hover and selection states. Columns sort when they define `sortValue`.
 */
export function DataTable<T>({
  rows,
  columns,
  onRow,
  selectedRow,
  rowKey,
  empty,
  className,
  maxHeight,
  minWidth = 640,
  initialSort,
  rowClassName,
}: {
  rows: T[]
  columns: Array<Column<T>>
  onRow?: (row: T) => void
  selectedRow?: (row: T) => boolean
  rowKey?: (row: T, index: number) => string
  empty?: ReactNode
  className?: string
  maxHeight?: string
  minWidth?: number
  initialSort?: { column: number; desc?: boolean }
  rowClassName?: (row: T) => string
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ? [{ id: `c${initialSort.column}`, desc: initialSort.desc ?? true }] : [])
  const tableColumns = useMemo<Array<ColumnDef<T>>>(() => columns.map((column, index) => ({
    id: `c${index}`,
    header: () => column.label,
    enableSorting: Boolean(column.sortValue),
    meta: { align: column.align, className: column.className, width: column.width } satisfies ColumnMeta,
    accessorFn: row => column.sortValue?.(row) ?? '',
    sortingFn: (left, right, id) => {
      const a = left.getValue(id) as string | number
      const b = right.getValue(id) as string | number
      if (typeof a === 'number' && typeof b === 'number')
        return a - b
      return String(a).localeCompare(String(b))
    },
    cell: info => column.render(info.row.original),
  })), [columns])
  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: rowKey ? (row, index) => rowKey(row, index) : undefined,
  })
  if (rows.length === 0)
    return <>{empty ?? <EmptyState title="No records" detail="Nothing matches the current filters." />}</>
  return (
    <div className={cn('min-w-0 overflow-auto', maxHeight, className)}>
      <table className="w-full border-collapse text-left text-[13px]" style={{ minWidth }}>
        <thead className="sticky top-0 z-10 bg-surface">
          {table.getHeaderGroups().map(group => (
            <tr key={group.id}>
              {group.headers.map(header => {
                const meta = header.column.columnDef.meta as ColumnMeta | undefined
                const sorted = header.column.getIsSorted()
                const canSort = header.column.getCanSort()
                return (
                  <th
                    key={header.id}
                    style={{ width: meta?.width }}
                    className={cn('h-9 border-b border-line px-3 text-[11.5px] font-medium whitespace-nowrap text-fg-subtle first:pl-4 last:pr-4', meta?.align === 'right' && 'text-right', meta?.align === 'center' && 'text-center')}
                  >
                    {canSort
                      ? (
                          <button className={cn('inline-flex items-center gap-1 hover:text-fg', sorted && 'text-fg')} onClick={header.column.getToggleSortingHandler()}>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === 'asc' ? <ArrowUp className="size-3" /> : sorted === 'desc' ? <ArrowDown className="size-3" /> : <ChevronsUpDown className="size-3 opacity-40" />}
                          </button>
                        )
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map(row => {
            const selected = selectedRow?.(row.original) ?? false
            return (
              <tr
                key={row.id}
                aria-selected={selected || undefined}
                tabIndex={onRow ? 0 : undefined}
                className={cn(
                  'group border-b border-line last:border-b-0 transition-colors',
                  onRow && 'cursor-pointer hover:bg-surface-2/70 focus-visible:bg-surface-2',
                  selected && 'bg-accent-soft/60 hover:bg-accent-soft',
                  rowClassName?.(row.original),
                )}
                onClick={() => onRow?.(row.original)}
                onKeyDown={event => {
                  if (onRow && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault()
                    onRow(row.original)
                  }
                }}
              >
                {row.getVisibleCells().map(cell => {
                  const meta = cell.column.columnDef.meta as ColumnMeta | undefined
                  return (
                    <td key={cell.id} className={cn('h-10 px-3 py-2 align-middle text-fg first:pl-4 last:pr-4', meta?.align === 'right' && 'tabular text-right', meta?.align === 'center' && 'text-center', meta?.className)}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
