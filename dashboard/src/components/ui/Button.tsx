import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
type Size = 'xs' | 'sm' | 'md' | 'icon' | 'icon-sm'

const variants: Record<Variant, string> = {
  primary: 'border-transparent bg-accent text-accent-fg shadow-card hover:bg-accent-hover',
  secondary: 'border-line bg-surface text-fg shadow-card hover:bg-surface-2 hover:border-line-strong',
  ghost: 'border-transparent bg-transparent text-fg-muted hover:bg-surface-2 hover:text-fg',
  subtle: 'border-transparent bg-surface-2 text-fg hover:bg-surface-3',
  danger: 'border-line bg-surface text-danger-text shadow-card hover:bg-danger-soft hover:border-danger/40',
}

const sizes: Record<Size, string> = {
  xs: 'h-6 gap-1 rounded-md px-2 text-xs',
  sm: 'h-7 gap-1.5 rounded-md px-2.5 text-[13px]',
  md: 'h-8 gap-2 rounded-lg px-3 text-[13px]',
  icon: 'size-8 rounded-lg',
  'icon-sm': 'size-7 rounded-md',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  className,
  children,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: ReactNode }) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex shrink-0 items-center justify-center border font-medium whitespace-nowrap transition-colors select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-3.5 [&_svg]:shrink-0',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn('inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-surface-2 px-1 font-sans text-[11px] font-medium text-fg-subtle', className)}>
      {children}
    </kbd>
  )
}
