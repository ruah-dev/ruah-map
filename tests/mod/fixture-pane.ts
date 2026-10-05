// Test data for ruah.test.ts: a hand-written .ruah/pane.json with three nodes and one flow.
// The mod reads this file from <repo>/.ruah/pane.json; render.py --pane writes the real one.

const svg = (w: number, h: number) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}">` +
  '<style>:root{--fg:#1f1e1d;--acc:#c4633f}/*THEME*/text{fill:var(--fg)}/*HL*/</style>' +
  '<g class="n N0"><rect x="10" y="10" width="120" height="40"/><text x="20" y="35">Web</text></g>' +
  '<g class="n N1"><rect x="200" y="10" width="120" height="40"/><text x="210" y="35">API</text></g>' +
  '<g class="n N2"><rect x="390" y="10" width="120" height="40"/><text x="400" y="35">Postgres</text></g>' +
  '<path class="e E0 E1" d="M130 30H200"/><path class="e E1 E2" d="M320 30H390"/>' +
  '</svg>'

const view = {
  svg: svg(520, 60), width: 520, height: 60,
  band: svg(520, 60), bandWidth: 520, bandHeight: 60,
  md: '### Code\n- **Web** · app → calls **API**\n- **API** · service → reads **Postgres**\n\n' +
    '### Infrastructure\n- **Postgres** · database',
  nodes: [0, 1, 2],
  edges: [[0, 1], [1, 2]],
  reps: { 0: 0, 1: 1, 2: 2 },
}

export const PANE_JSON = JSON.stringify({
  version: 1,
  repo: { name: 'fixture' },
  views: { overview: view, code: view, infra: view, all: view },
  nodes: {
    0: { id: 'pkg:apps/web', label: 'Web', layer: 'code', md: '#### Web' },
    1: { id: 'pkg:apps/api', label: 'API', layer: 'code', md: '#### API' },
    2: { id: 'tf:infra/aws_db_instance.main', label: 'Postgres', layer: 'infra', md: '#### Postgres' },
  },
  summary: null,
  insights: [],
  flows: [{ name: 'Checkout', steps: [0, 1, 2], notes: [null, 'POST /orders', null] }],
  counts: { code: 2, infra: 1, external: 0 },
})
