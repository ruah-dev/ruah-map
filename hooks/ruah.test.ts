import { expect, test } from 'claude-code/testing'

import { PANE_JSON } from './fixture-pane'

const PANE_PROPS = {
  title: 'ruah', isFocused: false, bodyColumns: 110, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 60 }, view: {},
}
const BAND_PROPS = {
  hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 110,
  scroll: { offset: 0, bodyRows: 30 }, view: {},
}

test('/ruah maps the repo into the band above the prompt, and moves to the side panel', async ($, on) => {
  const ran: string[][] = []
  const store = new Map<string, unknown>()
  on('session.cwd', async () => ({ value: '/repo/fixture' }))
  on('fs.read', async () => ({ value: PANE_JSON }))
  on('config.list', async () => ({ value: [{ key: 'theme', label: 'Theme', value: 'dark' }] }) as never)
  on('store.get', async (_$, e) => ({ value: store.get(e.key) }) as never)
  on('store.set', async (_$, e) => { store.set(e.key, e.value); return { value: undefined } as never })
  on('process.run', async (_$, e) => {
    ran.push([...e.argv])
    return { value: { exitCode: 0, stdout: 'ruah model → x\nrepo: fixture  nodes: 56  edges: 50', stderr: '',
      isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const opened: string[] = []
  on('ui.open', async (_$, e) => { opened.push(e.id); return { value: { isOpen: true } } as never })
  on('ui.close', async () => ({ value: undefined }) as never)

  const out = await $.command.run({ command: 'ruah', args: 'infra' })
  expect(out.text).toContain('nodes: 56')
  expect(ran[0]?.[1]).toMatch(/scan\.py$/)
  expect(ran[1]).toContain('--pane')
  expect(opened).toHaveLength(0) // the default place is the band, not a pane

  for (const surface of ['desktop', 'terminal'] as const) {
    const band = await $.ui.mount({ plugin: 'ruah', surface, component: 'AbovePrompt', props: BAND_PROPS })
    const tree = JSON.stringify(await band.drawn())
    expect(tree).toContain('fixture')
    if (surface === 'desktop') {
      const svg = JSON.stringify(await band.find({ type: 'Svg' }))
      expect(svg).toContain('--fg:#e8e7e2') // the app's dark theme reached the drawing
      expect(svg).not.toContain('/*THEME*/')
      await band.select({ key: 'flow', value: '0' })
      expect(JSON.stringify(await band.find({ type: 'Svg' }))).toContain('opacity:.2')
    } else {
      expect(await band.find({ type: 'Svg' as never })).toBeUndefined()
      expect(tree).toContain('Infrastructure')
    }
    await band.unmount()
  }

  // Side panel: the band yields, a pane opens, and the choice is remembered
  const band = await $.ui.mount({ plugin: 'ruah', surface: 'desktop', component: 'AbovePrompt', props: BAND_PROPS })
  await band.press({ key: 'move' })
  expect(opened).toContain('ruah')
  expect(store.get('place')).toBe('pane')
  await band.unmount()
  const pane = await $.ui.mount({ plugin: 'ruah', surface: 'desktop', component: 'Pane', requestId: 'ruah', props: PANE_PROPS })
  expect(await pane.find({ type: 'Svg' })).toBeDefined()
  await pane.press({ key: 'view-code' })
  await pane.unmount()

  const closed = await $.command.run({ command: 'ruah', args: 'close' })
  expect(closed.text).toContain('closed')
})
