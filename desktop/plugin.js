// hermes-spark Desktop half: status-bar chip + fleet panel, palette entries, opt-in DGX Spark theme.
// Talks only to this plugin's own REST namespace (/api/plugins/hermes-spark/*, dashboard/plugin_api.py).
// Loaded uncompiled: jsx()/jsxs() calls, no JSX syntax.
import {
  Button, host, haptic, PALETTE_AREA, Popover, PopoverContent, PopoverTrigger, requestTheme,
  STATUSBAR_AREAS, StatusDot, THEMES_AREA, useQuery, useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-spark'
const SPARK_GREEN = '#76b900'
const MODES = ['prefer-local', 'auto', 'prefer-cloud']
const KEY = [ID, 'status']

const TONE = { ok: 'good', degraded: 'warn', down: 'bad' }

function chipText(s) {
  if (!s) return 'spark · …'
  if (!s.nodes || !s.nodes.length) return 'spark · no nodes'
  return `spark · ${s.down ? 'down' : s.label} · ${s.mode}`
}

function NodeRow({ node, active }) {
  const h = node.last_health || {}
  const load = typeof h.load_proxy === 'number' ? h.load_proxy : null
  const tone = node.enabled === false ? 'muted' : TONE[h.status] || 'muted'
  return jsxs('div', {
    className: 'flex flex-col gap-1 rounded px-2 py-1.5',
    style: active ? { boxShadow: `inset 2px 0 0 ${SPARK_GREEN}` } : undefined,
    children: [
      jsxs('div', { className: 'flex items-center gap-2 text-xs', children: [
        jsx(StatusDot, { tone }),
        jsx('span', { className: 'font-medium', children: node.name }),
        jsx('span', { className: 'text-(--ui-text-tertiary)', children: node.kind }),
        jsx('span', { className: 'ml-auto tabular-nums text-(--ui-text-tertiary)',
          children: node.enabled === false ? 'disabled' : h.latency_ms != null ? `${h.latency_ms} ms` : h.status || 'unprobed' })
      ] }),
      load !== null && jsx('div', { className: 'h-1 w-full overflow-hidden rounded bg-(--ui-border)', title: `load ${load}`,
        children: jsx('div', { className: 'h-full', style: { width: `${Math.max(4, load * 100)}%`, background: load > 0.75 ? 'var(--ui-warning, #df6500)' : SPARK_GREEN } }) }),
      h.status && h.status !== 'ok' && h.detail && jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: h.detail })
    ]
  })
}

function Panel({ ctx, status }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')
  const run = async (label, path, body) => {
    setBusy(label)
    try {
      const next = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 30000 })
      qc.setQueryData(KEY, next)
      const d = next.decision || {}
      host.notify({ kind: d.warning ? 'warning' : 'success', title: 'Spark fleet',
        message: d.warning || d.reason || 'done', detail: d.applied ? 'Applies from the next message.' : undefined })
    } catch (err) {
      host.notifyError(err, 'Spark fleet request failed')
    } finally {
      setBusy('')
    }
  }
  const s = status || {}
  const activeId = (s.applied || {}).node_id
  return jsxs('div', { className: 'flex w-72 flex-col gap-2 p-2 text-xs', children: [
    jsxs('div', { className: 'flex items-center justify-between', children: [
      jsx('span', { className: 'font-medium', style: { color: SPARK_GREEN }, children: 'Spark fleet' }),
      jsx('span', { className: 'text-(--ui-text-tertiary)',
        children: s.applied && s.applied.kind ? (s.applied.kind === 'cloud' ? `cloud · ${s.applied.model}` : `${s.applied.node_name} · ${s.applied.model}`) : 'not routed yet' })
    ] }),
    jsx('div', { className: 'flex flex-col gap-0.5', children: (s.nodes || []).length
      ? s.nodes.map(n => jsx(NodeRow, { node: n, active: n.id === activeId }, n.id))
      : jsx('div', { className: 'text-(--ui-text-tertiary)', children: 'Add a box: hermes spark add --name gx10 --url http://<host>:11434/v1' }) }),
    jsx('div', { className: 'flex gap-1', role: 'radiogroup', 'aria-label': 'Routing mode', children: MODES.map(m =>
      jsx(Button, { key: m, size: 'micro', variant: s.mode === m ? 'default' : 'ghost', role: 'radio', 'aria-checked': s.mode === m,
        disabled: Boolean(busy), onClick: () => { haptic('tap'); run('mode', '/mode', { mode: m }) }, children: m })) }),
    jsxs('div', { className: 'flex gap-1', children: [
      jsx(Button, { size: 'micro', disabled: Boolean(busy), onClick: () => run('use', '/use', { node: 'freest' }),
        children: busy === 'use' ? 'Routing…' : 'Use freest' }),
      jsx(Button, { size: 'micro', variant: 'ghost', disabled: Boolean(busy), onClick: () => run('probe', '/probe'),
        children: busy === 'probe' ? 'Probing…' : 'Probe now' }),
      jsx(Button, { size: 'micro', variant: 'ghost', className: 'ml-auto', title: 'Switch to the DGX Spark theme',
        onClick: () => requestTheme('dgx-spark'), children: 'Spark look' })
    ] }),
    s.last_decision && s.last_decision.reason && jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
      children: `last: ${s.last_decision.reason}` })
  ] })
}

function Chip({ ctx }) {
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: KEY, queryFn: () => ctx.rest('/status'), refetchInterval: 15000, retry: 1, staleTime: 5000 })
  if (q.isError) {
    // Backend half not loaded (plugin disabled for the agent, or an older gateway): stay quiet.
    return jsx('span', { className: 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)', title: 'Enable hermes-spark and restart the gateway', children: 'spark · off' })
  }
  const s = q.data
  const local = s && !s.down && s.applied && s.applied.kind === 'local'
  return jsxs(Popover, { open, onOpenChange: setOpen, children: [
    jsx(PopoverTrigger, { asChild: true, children: jsxs(Button, {
      variant: 'ghost', size: 'micro', 'aria-label': 'Spark fleet', className: 'gap-1.5 text-[0.6875rem]',
      children: [
        jsx('span', { 'aria-hidden': true, style: { width: 6, height: 6, borderRadius: 999, display: 'inline-block',
          background: s && s.down ? 'var(--ui-destructive, #df6500)' : local ? SPARK_GREEN : 'var(--ui-text-tertiary)' } }),
        jsx('span', { children: chipText(s) })
      ]
    }) }),
    jsx(PopoverContent, { side: 'top', align: 'end', 'aria-label': 'Spark fleet', children: jsx(Panel, { ctx, status: s }) })
  ] })
}

const dgxSparkTheme = {
  name: 'dgx-spark',
  label: 'DGX Spark',
  description: 'Black and NVIDIA green, from hermes-spark',
  colors: {
    background: '#000000', foreground: '#ffffff',
    card: '#111111', cardForeground: '#ffffff', popover: '#111111', popoverForeground: '#ffffff',
    primary: SPARK_GREEN, primaryForeground: '#000000', secondary: '#1a1a1a', secondaryForeground: '#ffffff',
    muted: '#1a1a1a', mutedForeground: '#a7a7a7', accent: SPARK_GREEN, accentForeground: '#000000',
    border: '#2a2a2a', input: '#1a1a1a', ring: SPARK_GREEN, midground: SPARK_GREEN,
    destructive: '#df6500', destructiveForeground: '#000000', sidebarBackground: '#0a0a0a'
  }
}

export default {
  id: ID,
  name: 'Spark Fleet',
  description: 'Which Spark / Ollama box Hermes is routed to, its health, and one-click mode / freest switching.',
  defaultEnabled: true,
  register(ctx) {
    const post = async (path, body, label) => {
      try {
        const next = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 30000 })
        const d = next.decision || {}
        host.notify({ kind: d.warning ? 'warning' : 'info', title: label, message: d.warning || d.reason || 'done' })
      } catch (err) {
        host.notifyError(err, `${label} failed`)
      }
    }
    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 125, render: () => jsx(Chip, { ctx }) })
    ctx.register({ id: 'theme', area: THEMES_AREA, data: dgxSparkTheme })
    ctx.register({ id: 'palette-freest', area: PALETTE_AREA,
      data: { id: 'spark-use-freest', label: 'Spark: route to the freest box', keywords: ['spark', 'fleet', 'ollama', 'gpu'],
        run: () => post('/use', { node: 'freest' }, 'Spark: use freest') } })
    ctx.register({ id: 'palette-probe', area: PALETTE_AREA,
      data: { id: 'spark-probe', label: 'Spark: probe the fleet', keywords: ['spark', 'health'],
        run: () => post('/probe', {}, 'Spark: probe') } })
    for (const m of MODES) {
      ctx.register({ id: `palette-mode-${m}`, area: PALETTE_AREA,
        data: { id: `spark-mode-${m}`, label: `Spark: mode ${m}`, keywords: ['spark', 'mode', 'routing'],
          run: () => post('/mode', { mode: m }, `Spark: ${m}`) } })
    }
  }
}
