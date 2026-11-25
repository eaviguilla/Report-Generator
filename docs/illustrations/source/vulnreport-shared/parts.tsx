import { createContext, useContext, type CSSProperties, type ReactNode } from 'react'
import { Check as CheckIcon, ChevronDown, ChevronRight, Moon, Redo2, Undo2, type LucideIcon } from 'lucide-react'
import { Badge, Bar, Window } from '../../kit'
import { ENGAGEMENT, SEVERITY_LABEL, type Severity } from './data'
import { LOGO } from './logo'
import './look.css'

// Ghost mode turns every string into a bar, so the same page can stand in as a quiet neighbor
// of the page that has the words.
const GhostContext = createContext(false)
export const Ghost = GhostContext.Provider
export const useGhost = () => useContext(GhostContext)

export function T({ children, w, h = 7, tone = 2, fs = 12, className, style }: { children: string; w?: number; h?: number; tone?: 1 | 2 | 3 | 4 | 5; fs?: number; className?: string; style?: CSSProperties }) {
  if (useGhost()) return <Bar w={w ?? Math.round(children.length * fs * 0.5)} h={h} r={h / 2} tone={tone} className={className} style={style} />
  return <span className={className} style={style}>{children}</span>
}

// One family, one stroke weight: lucide at the kit's absolute stroke
export function Ico({ icon: Glyph, size = 14, stroke = 1.6, className }: { icon: LucideIcon; size?: number; stroke?: number; className?: string }) {
  return <Glyph size={size} strokeWidth={stroke} absoluteStrokeWidth className={className} aria-hidden />
}

export const Chevron = ({ down, size = 12 }: { down?: boolean; size?: number }) => <Ico icon={down ? ChevronDown : ChevronRight} size={size} stroke={1.8} className="vr-chevron" />

export function AppHeader({ name = ENGAGEMENT.name, chips, tools, saved = true }: { name?: string; chips?: string[]; tools?: boolean; saved?: boolean }) {
  return (
    <header className="vr-header">
      <span className="vr-brand">
        <img className="vr-logo" src={LOGO} alt="" width={26} height={26} />
        <T className="vr-brand__name" fs={13} w={100}>Report Generator</T>
      </span>
      <span className="vr-engagement">
        <T className="vr-engagement__name" fs={12} w={88}>{name}</T>
        {chips?.map((chip) => (
          <span key={chip} className="vr-chip" data-mono={chip.startsWith('CI-') || undefined}>
            <T fs={9.5} w={52}>{chip}</T>
          </span>
        ))}
      </span>
      <span className="vr-header__end">
        {tools && (
          <>
            <span className="vr-tool vr-tool--box"><Ico icon={Moon} size={14} /></span>
            <span className="vr-tool"><Ico icon={Undo2} size={14} /></span>
            <span className="vr-tool"><Ico icon={Redo2} size={14} /></span>
          </>
        )}
        {saved && <T className="vr-saved" fs={10.5} w={52}>{ENGAGEMENT.saved}</T>}
      </span>
    </header>
  )
}

const STEPS = ['Setup', 'Findings', 'Content']

export function Stepper({ active }: { active: 1 | 2 | 3 }) {
  return (
    <nav className="vr-stepper">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n < active ? 'done' : n === active ? 'active' : 'todo'
        return (
          <span key={label} className="vr-step" data-state={state}>
            <b>{n}</b>
            <T fs={state === 'done' ? 12 : 11} w={state === 'done' ? 30 : 42}>{label}</T>
          </span>
        )
      })}
    </nav>
  )
}

// The product in a browser window: chrome, then the app's own header, stepper and page
export function AppWindow({ step, url, ghost, wide, flush, chips, tools, name, className, style, children }: { step: 1 | 2 | 3; url?: string; ghost?: boolean; wide?: boolean; flush?: boolean; chips?: string[]; tools?: boolean; name?: string; className?: string; style?: CSSProperties; children: ReactNode }) {
  return (
    <Window url={url} urlShape="pill" lights={ghost ? 'grey' : 'color'} className={className} style={style}>
      <Ghost value={!!ghost}>
        <div className="vr-app" data-wide={wide || undefined} data-ghost={ghost || undefined}>
          <AppHeader chips={chips} tools={tools} name={name} />
          <Stepper active={step} />
          <div className="vr-page" data-flush={flush || undefined}>{children}</div>
        </div>
      </Ghost>
    </Window>
  )
}

// Severity is the only colored chip in the product, so the eye finds it first
export function SevPill({ level }: { level: Severity }) {
  return (
    <Badge dot className="vr-sev" data-sev={level}>
      <T fs={10.5} w={40}>{SEVERITY_LABEL[level]}</T>
    </Badge>
  )
}

export function Checkbox({ on }: { on?: boolean }) {
  return (
    <span className="vr-box" data-on={on || undefined}>
      {on && <Ico icon={CheckIcon} size={10} stroke={2.6} />}
    </span>
  )
}

export function Panel({ title, required, meta, mid, className, children }: { title: string; required?: boolean; meta?: string; mid?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`vr-panel${className ? ` ${className}` : ''}`}>
      <div className="vr-panel__head">
        <span className="vr-panel__title">
          <T fs={12} w={64}>{title}</T>
          {required && <i className="vr-req">*</i>}
        </span>
        {mid}
        {meta && <T className="vr-meta" fs={10} w={34}>{meta}</T>}
      </div>
      {children}
    </section>
  )
}
