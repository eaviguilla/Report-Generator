import { Fragment, type ReactNode } from 'react'
import { AlignLeft, Calendar, ChevronDown, ChevronRight, Code as CodeIcon, GripVertical, Image as ImageIcon, List, ListOrdered, Plus, Table, X } from 'lucide-react'
import { Bar, Button, Field, Row } from '../../kit'
import { API_TARGETS, CONTENT, ENGAGEMENT, FINDINGS, SEVERITY_LABEL, WEB_TARGETS, type Finding } from './data'
import { Checkbox, Chevron, Ghost, Ico, Panel, SevPill, T, useGhost } from './parts'

// A labelled field. In ghost mode the label and the value are bars.
function F({ label, value, required, select, date, className }: { label: string; value: string; required?: boolean; select?: boolean; date?: boolean; className?: string }) {
  const ghost = useGhost()
  return (
    <Field
      className={className}
      label={
        <>
          <T fs={11} w={Math.round(label.length * 5.4)}>{label}</T>
          {required && !ghost && <i className="vr-req">*</i>}
        </>
      }
      value={ghost ? '' : value}
      leading={ghost ? <Bar w={Math.min(96, 24 + value.length * 3.4)} h={6} r={3} tone={2} /> : undefined}
      trailing={select ? <Ico icon={ChevronDown} size={13} /> : date ? <Ico icon={Calendar} size={13} /> : undefined}
    />
  )
}

// A paragraph: real words, or a few bars of the same height
function Para({ children, lines = 3 }: { children: string; lines?: number }) {
  if (!useGhost()) return <p className="vr-para">{children}</p>
  const widths = ['100%', '92%', '96%', '70%', '84%']
  return (
    <div className="vr-para vr-para--ghost">
      {Array.from({ length: lines }, (_, i) => (
        <Bar key={i} w={widths[i % widths.length]} h={6} r={3} tone={2} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// Findings

const COLS_WIDE = 'minmax(0, 1fr) 72px 62px 100px 52px 92px 40px'
const COLS_NARROW = 'minmax(0, 1fr) 100px 78px'

function Locations() {
  return (
    <div className="vr-loc">
      <div className="vr-loc__head">
        <b>Affected Locations</b>
        <i>Added or modified locations do not affect the report scope.</i>
      </div>
      <div className="vr-loc__env">Production</div>
      <div className="vr-loc__cols">
        <div className="vr-loc__col">
          <div className="vr-loc__chan">Web</div>
          <div className="vr-loc__list">
            <label className="vr-loc__row"><Checkbox on /><span className="vr-area">{WEB_TARGETS[0]}</span></label>
            <label className="vr-loc__row"><Checkbox /><span className="vr-area">{WEB_TARGETS[1]}</span></label>
          </div>
        </div>
        <div className="vr-loc__col">
          <div className="vr-loc__chan">API</div>
          <div className="vr-loc__list">
            <label className="vr-loc__row"><Checkbox on /><span className="vr-area">{API_TARGETS[0]}</span></label>
          </div>
        </div>
      </div>
      <div className="vr-loc__chan">Additional affected endpoints</div>
      <span className="vr-area vr-area--hint">One endpoint per line</span>
    </div>
  )
}

export function FindingsPage({ wide, rows = FINDINGS, expand, ghostRows = 0 }: { wide?: boolean; rows?: Finding[]; expand?: number; ghostRows?: number }) {
  const cols = wide ? COLS_WIDE : COLS_NARROW
  return (
    <>
      <div className="vr-title">
        <div className="vr-h1">
          <T fs={22} h={12} w={84}>Findings</T>
          <small>{rows.length + ghostRows}</small>
        </div>
        {wide && expand !== undefined && <Button>Collapse all</Button>}
        <Field className="vr-search" value="" placeholder="Search or select a vulnerability" />
        <Button variant="primary" className="vr-green">Add finding</Button>
      </div>
      <div className="vr-table" style={{ ['--cols' as string]: cols }}>
        <div className="vr-tr vr-th">
          <T fs={10} w={34}>Finding</T>
          {wide && <T fs={10} w={52}>Likelihood</T>}
          {wide && <T fs={10} w={34}>Impact</T>}
          <T fs={10} w={44}>Severity</T>
          {wide && <T fs={10} w={40}>Vuln ID</T>}
          <T fs={10} w={32} className={wide ? 'vr-th__last' : undefined}>Status</T>
        </div>
        {rows.map((f, i) => (
          <Fragment key={f.name}>
            <div className="vr-tr vr-row" data-open={expand === i || undefined}>
              <span className="vr-name">
                <Chevron down={expand === i} />
                <T fs={12} w={Math.round(f.name.length * 6)}>{f.name}</T>
              </span>
              {wide && <span className="vr-mono">{f.likelihood}</span>}
              {wide && <span className="vr-mono">{f.impact}</span>}
              <SevPill level={f.severity} />
              {wide && <span className="vr-mono vr-dash">—</span>}
              <span className="vr-mono vr-status">
                <T fs={10.5} w={f.status.length * 5.4}>{f.status}</T>
                <Chevron down size={12} />
              </span>
              {wide && <span className="vr-delete">Delete</span>}
            </div>
            {expand === i && <Locations />}
          </Fragment>
        ))}
        {Array.from({ length: ghostRows }, (_, i) => (
          <div key={`g${i}`} className="vr-tr vr-row vr-row--ghost">
            <span className="vr-name">
              <Chevron />
              <Bar w={[132, 108, 150][i % 3]} h={7} r={3.5} tone={3} />
            </span>
            {wide && <Bar w={26} h={6} r={3} tone={2} />}
            {wide && <Bar w={26} h={6} r={3} tone={2} />}
            <Bar w={52} h={7} r={3.5} tone={2} />
            {wide && <Bar w={12} h={5} r={2.5} tone={2} />}
            <span className="vr-status"><Bar w={52} h={6} r={3} tone={2} /></span>
            {wide && <Bar w={40} h={6} r={3} tone={2} />}
          </div>
        ))}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------------------------
// Setup

function CoverRow({ wide }: { wide?: boolean }) {
  return (
    <div className="vr-cover__row" data-wide={wide || undefined}>
      <span className="vr-cover__env">
        <Checkbox on />
        <T fs={12} w={64} className="vr-strong">Production</T>
      </span>
      <F label="Start" value={ENGAGEMENT.start} date />
      <F label="End" value={ENGAGEMENT.end} date />
      <F label="Time" value="Anytime" />
    </div>
  )
}

function AppTypes() {
  return (
    <span className="vr-apptypes">
      <T fs={10.5} w={44} className="vr-strong">App Types</T>
      <span className="vr-apptype"><Checkbox on /><T fs={12} w={20} className="vr-strong">Web</T></span>
      <span className="vr-apptype"><Checkbox on /><T fs={12} w={16} className="vr-strong">API</T></span>
      <span className="vr-apptype"><Checkbox /><T fs={12} w={30} className="vr-strong">Mobile</T></span>
      <span className="vr-apptype"><Checkbox /><T fs={12} w={50} className="vr-strong">Thick Client</T></span>
    </span>
  )
}

export function SetupPage({ wide }: { wide?: boolean }) {
  const ghost = useGhost()
  return (
    <div className="vr-stack">
      <Panel title="Application" meta="4 of 4">
        <div className="vr-grid" style={{ ['--n' as string]: wide ? 4 : 2 }}>
          <F label="Application Name" value={ENGAGEMENT.name} required />
          <F label="Report Type" value={ENGAGEMENT.reportType} required select />
          <F label="Tester" value={ENGAGEMENT.tester} required />
          <F label="Report Date" value={ENGAGEMENT.reportDate} required date />
        </div>
      </Panel>
      <Panel title="Test Coverage" required meta="1 selected">
        <div className="vr-cover">
          <CoverRow wide={wide} />
        </div>
      </Panel>
      {!wide && (
        <Panel title="Test Accounts" meta="1 account">
          <div className="vr-grid" style={{ ['--n' as string]: 2 }}>
            <F label="User Role" value="Member" />
            <F label="Username" value="member.a@marlow-cu.example" />
          </div>
        </Panel>
      )}
      <Panel title="Scope" required meta="3 targets" mid={<AppTypes />}>
        <div className="vr-scope">
          {!wide && <T fs={10.5} w={300} className="vr-note">One target per line. Blank lines and lines beginning with # are ignored.</T>}
          <div className="vr-envbox">
            <T fs={12} w={64} className="vr-strong">Production</T>
            <div className="vr-envbox__cols">
              <div className="vr-envbox__col">
                <T fs={10.5} w={26} className="vr-chan">Web</T>
                {ghost ? <Bar w="100%" h={44} r={6} tone={1} /> : <span className="vr-area">{WEB_TARGETS.join('\n')}</span>}
              </div>
              <div className="vr-envbox__col">
                <T fs={10.5} w={22} className="vr-chan">API</T>
                {ghost ? <Bar w="100%" h={44} r={6} tone={1} /> : <span className="vr-area">{API_TARGETS.join('\n')}</span>}
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// Content

export function Block({ title, meta, collapsed, children }: { title: string; meta: string; collapsed?: boolean; children?: ReactNode }) {
  return (
    <section className="vr-block" data-collapsed={collapsed || undefined}>
      <div className="vr-block__head">
        <T fs={11.5} w={90} className="vr-strong">{title}</T>
        <T className="vr-meta" fs={9.5} w={50}>{meta}</T>
      </div>
      {!collapsed && <div className="vr-block__body">{children}</div>}
    </section>
  )
}

export function Fragmentish({ kind, tools = true, children }: { kind: string; tools?: boolean; children: ReactNode }) {
  return (
    <div className="vr-frag">
      <div className="vr-frag__head">
        <Ico icon={GripVertical} size={11} stroke={1.4} />
        <T fs={9.5} w={40} className="vr-meta">{kind}</T>
        {tools && (
          <span className="vr-frag__tools">
            <Ico icon={X} size={11} stroke={1.4} />
          </span>
        )}
      </div>
      <div className="vr-frag__body">{children}</div>
    </div>
  )
}

function AddBar() {
  return (
    <div className="vr-addbar">
      <span className="vr-addbar__add"><Ico icon={Plus} size={12} stroke={1.8} /><T fs={11} w={22}>Add</T></span>
      <i />
      <Ico icon={AlignLeft} size={13} />
      <Ico icon={ListOrdered} size={13} />
      <Ico icon={List} size={13} />
      <i />
      <Ico icon={ImageIcon} size={13} />
      <Ico icon={Table} size={13} />
      <Ico icon={CodeIcon} size={13} />
    </div>
  )
}

export function ContentPage({ wide, quiet, children }: { wide?: boolean; quiet?: boolean; children?: ReactNode }) {
  const ghost = useGhost()
  return (
    <div className="vr-content" data-wide={wide || undefined}>
      <Ghost value={ghost || !!quiet}>
        <aside className="vr-nav">
          <NavHead />
          {FINDINGS.map((f, i) => (
            <NavItem key={f.name} finding={f} on={i === 0} />
          ))}
          <div className="vr-nav__group">
            <ChevronRight size={11} strokeWidth={1.8} absoluteStrokeWidth />
            <T fs={10.5} w={96} className="vr-strong">Engagement scope</T>
          </div>
        </aside>
      </Ghost>
      <div className="vr-editor">
        <div className="vr-etitle">
          <T fs={17} h={10} w={196}>{CONTENT.title}</T>
        </div>
        <div className="vr-chips">
          <SevPill level="critical" />
          <span className="vr-fchip"><T fs={10} w={50}>Likelihood</T>{!ghost && <b>high</b>}</span>
          <span className="vr-fchip"><T fs={10} w={32}>Impact</T>{!ghost && <b>critical</b>}</span>
          {wide && <span className="vr-fchip"><T fs={10} w={50}>Open (New)</T></span>}
        </div>
        {children ?? (
          <>
            <Block title="Description" meta="1 fragment">
              <Fragmentish kind="paragraph">
                <Para>{CONTENT.description}</Para>
              </Fragmentish>
              <AddBar />
            </Block>
            <Block title="Recommended Remediation" meta="1 fragment">
              <Fragmentish kind="paragraph">
                <Para lines={2}>{CONTENT.remediation}</Para>
              </Fragmentish>
            </Block>
          </>
        )}
      </div>
    </div>
  )
}

function NavHead() {
  const ghost = useGhost()
  return (
    <div className="vr-nav__head">
      <T fs={11} w={40} className="vr-strong">Findings</T>
      {ghost ? <Bar w={10} h={5} r={2.5} tone={2} /> : <small>{FINDINGS.length}</small>}
    </div>
  )
}

function NavItem({ finding, on }: { finding: Finding; on?: boolean }) {
  const ghost = useGhost()
  return (
    <div className="vr-nav__item" data-sev={finding.severity} data-on={on || undefined}>
      <Row
        pad={10}
        title={<T fs={11.5} w={Math.round(finding.name.length * 5.6)} className="vr-nav__name">{finding.name}</T>}
        subtitle={
          <span className="vr-nav__sub">
            <T fs={9.5} w={32}>{SEVERITY_LABEL[finding.severity].toUpperCase()}</T>
            {!ghost && ' · '}
            <T fs={9.5} w={26}>No ID</T>
          </span>
        }
      />
    </div>
  )
}
