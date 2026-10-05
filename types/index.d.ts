export type RuahView = 'overview' | 'code' | 'infra' | 'all'
export type RuahPlace = 'band' | 'pane'

declare module 'claude-code' {
  interface PluginState {
    'ruah': {
      repo: string
      view: RuahView
      flow: number
      focus: number
      stamp: number
      busy: string
      place: RuahPlace
      isOpen: boolean
    }
  }
}
