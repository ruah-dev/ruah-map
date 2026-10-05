import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { RuahPlace, RuahView } from '../types'

// ruah: code + cloud architecture map inside Claude Code.
//   /ruah [overview|code|infra|all] [path]   scan and show the map (no model call)
//   /ruah deep | live <aws,gcp,azure,k8s> | md   hand the analysis to Claude (the ruah:map skill)
//   /ruah side | above | close
// The map sits in the band above the prompt by default; "Side panel" moves it to a docked pane
// and back, and the choice is remembered across sessions. The model refreshes it with `show`.

const PANE = 'ruah'
const VIEWS: RuahView[] = ['overview', 'code', 'infra', 'all']
const VIEW_LABEL: Record<RuahView, string> = { overview: 'Overview', code: 'Code', infra: 'Infra', all: 'All' }
const PX_PER_COLUMN = 8 // the desktop surface's monospace cell, roughly

const repo = atom({ plugin: 'ruah', key: 'repo' } as const, '')
const view = atom({ plugin: 'ruah', key: 'view' } as const, 'overview' as RuahView)
const flow = atom({ plugin: 'ruah', key: 'flow' } as const, -1)
const focus = atom({ plugin: 'ruah', key: 'focus' } as const, -1)
const stamp = atom({ plugin: 'ruah', key: 'stamp' } as const, 0)
const busy = atom({ plugin: 'ruah', key: 'busy' } as const, '')
const place = atom({ plugin: 'ruah', key: 'place' } as const, 'band' as RuahPlace)
const isOpen = atom({ plugin: 'ruah', key: 'isOpen' } as const, false)

type PaneView = {
  svg: string | null
  width: number
  height: number
  band: string | null
  bandWidth: number
  bandHeight: number
  md: string
  nodes: number[]
  edges: [number, number][]
  reps: Record<string, number>
}
type PaneData = {
  repo: { name?: string; git?: { branch?: string; commit?: string } }
  stack?: { languages?: Record<string, number>; frameworks?: string[] }
  views: Record<RuahView, PaneView>
  nodes: Record<string, { id: string; label: string; layer: string; md: string }>
  summary?: string | null
  insights: { title: string; severity: string; body: string; nodes: number[] }[]
  flows: { name: string; description?: string; steps: number[]; notes: (string | null)[] }[]
  counts: Record<string, number>
}

// module-level caches only; a reload re-reads
let cache: { key: string; data: PaneData | null } = { key: '', data: null }
let themeBlock: string | null = null

const DARK = ':root{--fg:#e8e7e2;--mut:#8f8e88;--node:rgba(255,255,255,.035);--nodeb:rgba(255,255,255,.1);' +
  '--grp:rgba(255,255,255,.018);--grpb:rgba(255,255,255,.065);--edge:rgba(255,255,255,.22);--acc:#d97757}'
const LIGHT = ':root{--fg:#1f1e1d;--mut:#8a8984;--node:rgba(31,30,29,.035);--nodeb:rgba(31,30,29,.13);' +
  '--grp:rgba(31,30,29,.022);--grpb:rgba(31,30,29,.08);--edge:rgba(31,30,29,.26);--acc:#c4633f}'

async function theme($: any): Promise<string> {
  if (themeBlock !== null) return themeBlock
  try {
    const row = (await $.config.list()).find((r: { key: string }) => r.key === 'theme') as { value?: unknown } | undefined
    const v = String(row?.value ?? '')
    themeBlock = /light/i.test(v) ? LIGHT : /dark/i.test(v) ? DARK : ''
  } catch {
    themeBlock = ''
  }
  return themeBlock
}

async function loadData($: any, dir: string, st: number): Promise<PaneData | null> {
  const key = `${dir}:${st}`
  if (cache.key === key) return cache.data
  try {
    cache = { key, data: JSON.parse(await $.fs.read(`${dir}/.ruah/pane.json`)) as PaneData }
  } catch {
    cache = { key, data: null }
  }
  return cache.data
}

/** scan (optional) + render pane.json; returns the scanner's one-line summary */
async function build($: any, dir: string, v: RuahView, rescan: boolean): Promise<string> {
  const s = `${$.plugin.root}/scripts`
  let summary = ''
  if (rescan) {
    await update($, busy, () => 'Scanning…')
    // python3 <plugin>/scripts/scan.py <repo>: reads the repo, writes <repo>/.ruah/model.json
    const scan = await $.process.run(['python3', `${s}/scan.py`, dir], { cwd: dir, timeoutMs: 300_000 })
    if (scan.exitCode !== 0) {
      await update($, busy, () => '')
      throw new Error(scan.stderr.trim().split('\n').slice(-1)[0] || 'scan failed')
    }
    summary = (scan.stdout.split('\n')[1] ?? '').replace(/^repo:\s*/, '')
  }
  await update($, busy, () => 'Drawing…')
  // python3 <plugin>/scripts/render.py <repo>/.ruah --pane --view <view>: writes <repo>/.ruah/pane.json
  const r = await $.process.run(['python3', `${s}/render.py`, `${dir}/.ruah`, '--pane', '--view', v], { cwd: dir, timeoutMs: 300_000 })
  await update($, busy, () => '')
  if (r.exitCode !== 0) throw new Error(r.stderr.trim().split('\n').slice(-1)[0] || 'render failed')
  await update($, stamp, n => (n ?? 0) + 1)
  return summary
}

async function present($: any, where: RuahPlace) {
  await update($, place, () => where)
  await $.store.set('place', where)
  if (where === 'pane') {
    await update($, isOpen, () => false)
    const dir = await read($, repo)
    // the drawn (possibly redacted) name, never the folder name: a map may be shown publicly
    const data = dir ? await loadData($, dir, await read($, stamp)) : null
    await $.ui.open({ id: PANE, title: `ruah · ${data?.repo.name ?? 'map'}` })
  } else {
    await $.ui.close({ id: PANE }).catch(() => undefined)
    await update($, isOpen, () => true)
  }
}

async function show($: any, dir: string, v: RuahView, rescan: boolean) {
  await update($, repo, () => dir)
  await update($, view, () => v)
  await update($, flow, () => -1)
  await update($, focus, () => -1)
  const summary = await build($, dir, v, rescan)
  await present($, await read($, place))
  return summary
}

function analyzePrompt(dir: string, sub = 'deep') {
  return `Use the ruah:map skill with arguments: ${sub} ${dir}\n` +
    'When enrich.json is written, call the mcp__ruah__show tool with this path so the map refreshes.'
}

/** Light the focused node and its neighbours, or a flow's path; everything else recedes. */
function lit(svg: string, pv: PaneView, data: PaneData, fl: number, fo: number): string {
  const nodes = new Set<number>()
  const edgeRules: string[] = []
  if (fl >= 0 && data.flows[fl]) {
    const steps = data.flows[fl].steps.map(s => pv.reps[String(s)] ?? s)
    steps.forEach(s => nodes.add(s))
    steps.slice(1).forEach((t, k) => edgeRules.push(`.E${steps[k]}.E${t}`))
  } else if (fo >= 0) {
    const r = pv.reps[String(fo)] ?? fo
    nodes.add(r)
    pv.edges.forEach(([a, b]) => { if (a === r) nodes.add(b); if (b === r) nodes.add(a) })
    edgeRules.push(`.E${r}`)
  }
  if (!nodes.size) return svg
  const css = '.n,.e,.el{opacity:.2}' + [...nodes].map(i => `.n.N${i}`).join(',') + '{opacity:1}' +
    (edgeRules.length ? edgeRules.map(r => `.e${r},.el${r}`).join(',') + '{opacity:1;stroke:var(--acc)}' : '')
  return svg.replace('/*HL*/', css)
}

/** The map's body, shared by the band above the prompt and the side panel. */
async function body($: any, e: any, where: RuahPlace, room: { columns: number; maxPx: number }) {
  const els = $.ui.resolve(e)
  const { Box, Text, Button, Markdown, Select } = els
  const Svg = e.surface === 'terminal' ? undefined : els.Svg
  const dir = await read($, repo)
  const data = dir ? await loadData($, dir, await read($, stamp)) : null
  const v = (await read($, view)) as RuahView
  const fl = await read($, flow)
  const fo = await read($, focus)
  const working = await read($, busy)
  const close = where === 'band'
    ? () => { void update($, isOpen, () => false) }
    : () => { void $.ui.close({ id: PANE }) }

  if (!data) {
    return (
      <Box flexDirection="row" gap={1}>
        <Text dimColor>{working || 'No map yet. Run /ruah in a repository.'}</Text>
      </Box>
    )
  }
  const pv = data.views[v]
  const nodes = data.nodes
  const git = data.repo.git ? `${data.repo.git.branch} · ${data.repo.git.commit}` : ''
  const counts = `${data.counts.code ?? 0} code · ${data.counts.infra ?? 0} infra · ${data.counts.external ?? 0} external`

  // the drawing: band variant (wide and short) above the prompt, full layout in the panel
  let svg = where === 'band' ? (pv.band ?? pv.svg) : (pv.svg ?? pv.band)
  const w0 = where === 'band' && pv.band ? pv.bandWidth : pv.width
  const h0 = where === 'band' && pv.band ? pv.bandHeight : pv.height
  let width = 0
  let height = 0
  if (svg) {
    svg = lit(svg.replace('/*THEME*/', await theme($)), pv, data, fl, fo)
    const avail = Math.max(240, room.columns * PX_PER_COLUMN - 16)
    const fitW = Math.min(1, avail / w0)
    const fitH = Math.min(1, room.maxPx / h0)
    // fit the box when that keeps text readable; otherwise fit the width and let the site scroll
    const scale = fitH >= 0.55 ? Math.min(fitW, fitH) : fitW
    width = Math.round(w0 * scale)
    height = Math.round(h0 * scale)
  }

  let details = ''
  if (fl >= 0 && data.flows[fl]) {
    const f = data.flows[fl]
    details = f.steps.map((s, k) => `${k + 1}. **${nodes[String(s)]?.label ?? s}**${f.notes[k] ? ` · ${f.notes[k]}` : ''}`).join('\n')
  } else if (fo >= 0 && nodes[String(fo)]) {
    details = nodes[String(fo)].md
  } else if (where === 'pane') {
    details = [data.summary ?? '',
      data.insights.map(i => `- **${i.title}** · ${i.body}`).join('\n')].filter(Boolean).join('\n\n')
  }
  const hint = data.summary ? '' : 'Run /ruah deep for descriptions, code↔infra links, flows and risks.'

  const nodeOptions = pv.nodes
    .filter(i => nodes[String(i)])
    .map(i => ({ value: String(i), label: nodes[String(i)].label }))
    .sort((a, b) => a.label.localeCompare(b.label))
    .slice(0, 63) // a Select takes at most 64 options, "None" included

  return (
    <Box flexDirection="column" gap={1}>
      <Box flexDirection="row" justifyContent="space-between" gap={2}>
        <Box flexDirection="row" gap={1} flexShrink={1}>
          <Text bold wrap="truncate">{data.repo.name ?? 'repository'}</Text>
          <Text dimColor wrap="truncate">{[git, counts, working].filter(Boolean).join('  ·  ')}</Text>
        </Box>
        <Box flexDirection="row" gap={1}>
          <Button key="move" plain dimColor label={where === 'band' ? 'Side panel' : 'Above prompt'}
            onPress={() => { void present($, where === 'band' ? 'pane' : 'band') }} />
          <Button key="close" plain dimColor role="dismiss" label="Close" onPress={close} />
        </Box>
      </Box>
      <Box flexDirection="row" gap={1} flexWrap="wrap" alignItems="center">
        {VIEWS.map((name, k) => (
          <Button key={`view-${name}`} label={VIEW_LABEL[name]} hotkey={String(k + 1)}
            variant={name === v ? 'primary' : 'secondary'}
            onPress={() => { void update($, view, () => name); void update($, focus, () => -1); void update($, flow, () => -1) }} />
        ))}
        {Select && nodeOptions.length > 0 && (
          <Select key="focus" label="Focus" value={String(fo)}
            options={[{ value: '-1', label: 'None' }, ...nodeOptions]}
            onSelect={(val: string) => { void update($, focus, () => Number(val)); void update($, flow, () => -1) }} />
        )}
        {Select && data.flows.length > 0 && (
          <Select key="flow" label="Flow" value={String(fl)}
            options={[{ value: '-1', label: 'None' }, ...data.flows.map((f, i) => ({ value: String(i), label: f.name }))]}
            onSelect={(val: string) => { void update($, flow, () => Number(val)); void update($, focus, () => -1) }} />
        )}
        <Button key="rescan" plain dimColor label="Rescan" hotkey="r"
          onPress={() => { void show($, dir, v, true).catch((err: Error) => $.ui.toast(`ruah: ${err.message}`)) }} />
        <Button key="deep" plain dimColor label="Analyze" hotkey="a"
          onPress={() => { void $.prompt.submit({ text: analyzePrompt(dir) }) }} />
      </Box>
      {Svg && svg
        ? <Svg source={svg} width={width} height={height}
            alt={`${VIEW_LABEL[v]} architecture map of ${data.repo.name ?? 'the repository'}`} />
        : <Markdown text={(pv.md || '_Nothing in this view._').slice(0, where === 'band' ? 2500 : 9000)} />}
      {details
        ? <Markdown text={details.slice(0, where === 'band' ? 1200 : 9000)} />
        : hint ? <Text dimColor>{hint}</Text> : null}
    </Box>
  )
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const saved = await $.store.get('place')
    if (saved === 'band' || saved === 'pane') await update($, place, () => saved)
    await $.command.register({
      name: 'ruah',
      description: 'Architecture map of this repo (code + cloud infra)',
      argumentHint: '[overview|code|infra|all|deep|live aws|md|side|above|close] [path]',
    })
    await $.tool.register({
      name: 'show',
      description:
        'Open or refresh the ruah architecture map for a repository inside the app. Call it after writing or ' +
        'changing <repo>/.ruah/enrich.json (or after a ruah scan) so the person sees the updated map.',
      inputSchema: {
        type: 'object',
        properties: {
          path: { type: 'string', description: 'Absolute repository path (the folder that contains .ruah/)' },
          view: { type: 'string', enum: VIEWS },
          rescan: { type: 'boolean', description: 'Re-run the scanner first (default false)' },
        },
        required: ['path'],
      },
    })
    return next(e)
  })

  on('command.run', { command: 'ruah' }, async ($, e) => {
    const words = (e.args ?? '').trim().split(/\s+/).filter(Boolean)
    const sub = (words[0] ?? 'overview').toLowerCase()
    const cwd = await $.session.cwd()
    const pathWord = words.find(w => w.startsWith('/') || w.startsWith('./') || w.startsWith('../'))
    const dir = pathWord ? (pathWord.startsWith('/') ? pathWord : `${cwd}/${pathWord}`) : cwd

    if (sub === 'close') {
      await update($, isOpen, () => false)
      await $.ui.close({ id: PANE }).catch(() => undefined)
      return { text: 'Map closed.' }
    }
    if (sub === 'side' || sub === 'above') {
      if (!(await read($, repo))) await update($, repo, () => dir)
      await present($, sub === 'side' ? 'pane' : 'band')
      return { text: sub === 'side' ? 'Map moved to the side panel.' : 'Map moved above the prompt.' }
    }
    if (sub === 'deep' || sub === 'live' || sub === 'md') {
      const arg = sub === 'live' ? `live ${words[1] && !words[1].startsWith('/') ? words[1] : 'aws'}` : sub
      try { await show($, dir, sub === 'live' ? 'infra' : 'overview', true) } catch { /* the skill rescans */ }
      await $.prompt.submit({ text: analyzePrompt(dir, arg) })
      return { text: `Map open. Claude is running the ${arg} analysis.` }
    }
    const v: RuahView = VIEWS.includes(sub as RuahView) ? (sub as RuahView) : 'overview'
    try {
      const summary = await show($, dir, v, true)
      return { text: summary || 'Map ready.' }
    } catch (err) {
      return { text: `ruah could not map this folder: ${(err as Error).message}`, exitCode: 1 }
    }
  })

  on('tool.call', { tool: 'mcp__ruah__show' }, async ($, e) => {
    const input = e as unknown as { path?: string; view?: RuahView; rescan?: boolean }
    const dir = input.path || (await $.session.cwd())
    const v = VIEWS.includes(input.view as RuahView) ? (input.view as RuahView) : 'overview'
    try {
      const summary = await show($, dir, v, input.rescan === true)
      return { result: `Map refreshed in the app for ${dir} (${v}). ${summary}`.trim() }
    } catch (err) {
      return { result: `ruah could not draw the map: ${(err as Error).message}`, isError: true } as never
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || !(await read($, isOpen)) || (await read($, place)) !== 'band') return next(e)
    const rows = e.props.maxRows ?? 24
    return body($, e, 'band', { columns: e.props.bodyColumns ?? 100, maxPx: Math.min(440, Math.max(160, (rows - 5) * 18)) })
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    return body($, e, 'pane', { columns: e.props.bodyColumns ?? 100, maxPx: 4000 })
  })
}
