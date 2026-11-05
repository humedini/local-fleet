// local-fleet Desktop half: status-bar chip + fleet panel, palette entries, opt-in DGX Spark theme.
// Talks only to this plugin's own REST namespace (/api/plugins/local-fleet/*, dashboard/plugin_api.py).
// Loaded uncompiled: jsx()/jsxs() calls, no JSX syntax. Styling is theme tokens; Spark green only
// marks fleet-owned state (routed locally, load meters).
import {
  Button, COMPOSER_AREAS, host, haptic, MODEL_MENU_ROW_AREA, PALETTE_AREA, Popover, PopoverContent, PopoverTrigger, ROUTES_AREA,
  SIDEBAR_NAV_AREA, STATUSBAR_AREAS, THEMES_AREA, useQuery, useQueryClient, useTheme
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'local-fleet'
const SPARK_GREEN = '#76b900'
const MODES = [['prefer-local', 'Local'], ['auto', 'Auto'], ['prefer-cloud', 'Cloud']]
const KEY = [ID, 'status']
const PAGE_PATH = '/local-fleet'
const AUTO_PICK_TIP = 'Switch Hermes to the least busy box that has your model (loads the model there first)'
// Last status seen by any view, for the model menu and pill (their decorators must be pure lookups).
let LAST = null

const CSS = `
.hs-chip{display:inline-flex;align-items:center;gap:6px}
.hs-marks{display:inline-flex;align-items:center;gap:3px;flex-shrink:0}
.hs-marks svg{display:block}
.hs-tps{color:var(--ui-text-secondary);font-variant-numeric:tabular-nums}
.hs-dot{width:7px;height:7px;border-radius:999px;flex-shrink:0;background:var(--ui-text-quaternary)}
.hs-dot[data-tone=ok]{background:color-mix(in srgb,${SPARK_GREEN} 75%,var(--ui-text-tertiary))}
.hs-dot[data-tone=spark]{background:${SPARK_GREEN};box-shadow:0 0 0 2px color-mix(in srgb,${SPARK_GREEN} 25%,transparent)}
.hs-dot[data-tone=warn]{background:var(--ui-orange,#df6500)}
.hs-dot[data-tone=bad]{background:var(--ui-red,#e5484d)}
.hs-pop{width:340px;max-width:calc(100vw - 24px);padding:6px}
.hs-panel{padding:2px 0 0;font-size:12px;color:var(--ui-text-primary)}
.hs-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding:2px 8px 0}
.hs-title{font-weight:600;color:${SPARK_GREEN}}
.hs-mode-tag{font-size:11px;color:var(--ui-text-tertiary)}
.hs-route{padding:2px 8px 8px;font-size:11px;color:var(--ui-text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-route b{font-weight:500;color:var(--ui-text-primary)}
.hs-list{display:flex;flex-direction:column;gap:1px;border-top:1px solid var(--ui-stroke-tertiary);border-bottom:1px solid var(--ui-stroke-tertiary);padding:4px 0}
.hs-row{display:grid;grid-template-columns:10px minmax(0,1fr) auto;column-gap:8px;row-gap:3px;align-items:center;padding:5px 8px;border-radius:5px}
.hs-row[data-active=true]{background:var(--ui-row-active-background)}
.hs-row[data-skipped=true] .hs-name,.hs-row[data-skipped=true] .hs-sub{opacity:.55}
.hs-name{display:flex;align-items:center;gap:6px;min-width:0;font-weight:500}
.hs-name span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-badge[data-kind=freest]{color:${SPARK_GREEN};border-color:color-mix(in srgb,${SPARK_GREEN} 50%,transparent)}
.hs-badge{font-size:10px;font-weight:500;padding:0 5px;border-radius:999px;line-height:15px;color:var(--ui-text-secondary);border:1px solid var(--ui-stroke-secondary)}
.hs-badge[data-kind=active]{color:#000;background:${SPARK_GREEN};border-color:${SPARK_GREEN}}
.hs-lat{font-size:11px;font-variant-numeric:tabular-nums;color:var(--ui-text-tertiary)}
.hs-sub{grid-column:2 / 4;display:flex;align-items:center;gap:8px;font-size:11px;color:var(--ui-text-tertiary)}
.hs-meter{flex:0 0 72px;height:4px;border-radius:999px;background:var(--ui-stroke-tertiary);overflow:hidden}
.hs-meter>i{display:block;height:100%;border-radius:999px;background:${SPARK_GREEN}}
.hs-meter[data-busy=true]>i{background:var(--ui-orange,#df6500)}
.hs-sub-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-controls{display:flex;flex-direction:column;gap:8px;padding:8px 8px 4px}
.hs-seg{display:grid;grid-template-columns:repeat(3,1fr);padding:2px;border-radius:7px;background:var(--ui-bg-tertiary,rgba(127,127,127,.12))}
.hs-seg button{all:unset;cursor:pointer;text-align:center;font-size:11px;line-height:22px;border-radius:5px;color:var(--ui-text-secondary)}
.hs-seg button:hover{color:var(--ui-text-primary)}
.hs-seg button[aria-checked=true]{background:var(--ui-bg-elevated,var(--ui-bg-card));color:var(--ui-text-primary);box-shadow:0 0 0 1px var(--ui-stroke-secondary)}
.hs-seg button:disabled{cursor:default;opacity:.6}
.hs-actions{display:flex;gap:6px}
.hs-actions>*{flex:1}
.hs-foot{display:flex;justify-content:space-between;gap:8px;padding:2px 8px 4px;font-size:10.5px;color:var(--ui-text-quaternary)}
.hs-link{all:unset;cursor:pointer;color:var(--ui-text-tertiary)}
.hs-link:hover{color:${SPARK_GREEN}}
.hs-error{padding:0 8px 6px;color:var(--ui-text-secondary)}
.hs-error code{display:block;margin-top:4px;font-size:11px;color:var(--ui-text-tertiary);word-break:break-word}
.hs-page{height:100%;overflow-y:auto;padding:20px 24px 32px;color:var(--ui-text-primary)}
.hs-page-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:14px}
.hs-page-head h1{font-size:22px;font-weight:600;margin:0}
.hs-page-head h1 span{color:${SPARK_GREEN}}
.hs-page-hint{font-size:12px;color:var(--ui-text-tertiary)}
.hs-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}
.hs-stat{border:1px solid var(--ui-stroke-tertiary);border-radius:8px;padding:10px 14px;min-width:0}
.hs-stat b{display:block;font-size:20px;font-weight:600;line-height:26px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-stat span{font-size:12px;color:var(--ui-text-tertiary)}
.hs-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.hs-toolbar .hs-seg{width:260px}
.hs-map{position:relative;border:1px solid var(--ui-stroke-tertiary);border-radius:10px;background:radial-gradient(ellipse at 30% 40%,color-mix(in srgb,${SPARK_GREEN} 6%,transparent),transparent 60%);overflow:hidden}
.hs-map svg{display:block;width:100%;height:auto}
.hs-map text{fill:var(--ui-text-primary);font-size:12px}
.hs-map .t2{fill:var(--ui-text-tertiary);font-size:10.5px}
.hs-map .t3{fill:var(--ui-text-quaternary);font-size:10px;letter-spacing:.08em}
.hs-wire{fill:none;stroke:var(--ui-stroke-secondary);stroke-width:1.2}
.hs-wire[data-off=true]{stroke-dasharray:3 5;opacity:.5}
.hs-wire[data-live=true]{stroke:${SPARK_GREEN};stroke-width:2.2;stroke-dasharray:8 6;animation:hs-flow 0.9s linear infinite}
.hs-wire[data-traffic=true]{stroke:color-mix(in srgb,${SPARK_GREEN} 70%,#6ee7ff);stroke-width:1.8;stroke-dasharray:3 5;animation:hs-flow 0.6s linear infinite}
.hs-wire[data-cloud=true]{stroke-dasharray:5 6}
.hs-toggle{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--ui-text-secondary);padding:3px 4px}
.hs-toggle i{width:26px;height:14px;border-radius:999px;background:var(--ui-stroke-secondary);position:relative;transition:background .15s}
.hs-toggle i::after{content:'';position:absolute;top:2px;left:2px;width:10px;height:10px;border-radius:999px;background:var(--ui-text-primary);transition:transform .15s}
.hs-toggle[aria-checked=true]{color:var(--ui-text-primary)}
.hs-toggle[aria-checked=true] i{background:${SPARK_GREEN}}
.hs-toggle[aria-checked=true] i::after{transform:translateX(12px);background:#000}
.hs-wire[data-cloud=true][data-live=true]{stroke:var(--ui-orange,#df6500)}
@keyframes hs-flow{to{stroke-dashoffset:-28}}
.hs-led{animation:hs-blink 1.8s ease-in-out infinite}
.hs-led:nth-child(2n){animation-delay:.6s}
.hs-led:nth-child(3n){animation-delay:1.1s}
@keyframes hs-blink{0%,100%{opacity:1}50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.hs-wire[data-live=true],.hs-led{animation:none}}
.hs-page{container-type:inline-size}
.hs-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}
@container (max-width:900px){.hs-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@container (max-width:560px){.hs-cards{grid-template-columns:minmax(0,1fr)}}
.hs-card{border:1px solid var(--ui-stroke-tertiary);border-radius:8px;padding:10px 12px;min-width:0}
.hs-card[data-active=true]{border-color:${SPARK_GREEN};box-shadow:0 0 0 1px color-mix(in srgb,${SPARK_GREEN} 40%,transparent)}
.hs-card-head{display:flex;align-items:center;gap:7px;font-weight:600}
.hs-card-head .hs-lat{margin-left:auto;font-weight:400}
.hs-card-perf{font-size:11px;color:var(--ui-text-tertiary);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-card-perf b{font-size:16px;font-weight:600;color:var(--ui-text-primary);font-variant-numeric:tabular-nums}
.hs-card-sub{font-size:11px;color:var(--ui-text-tertiary);margin:2px 0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-card .hs-spark{display:block;width:100%;height:38px;margin-top:4px}
.hs-models{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.hs-models span{font-size:10.5px;padding:1px 6px;border-radius:4px;background:var(--ui-bg-tertiary,rgba(127,127,127,.12));color:var(--ui-text-secondary)}
.hs-models span[data-want=true]{color:#000;background:${SPARK_GREEN}}
.hs-models span[data-fallback=true]{color:${SPARK_GREEN};box-shadow:inset 0 0 0 1px color-mix(in srgb,${SPARK_GREEN} 60%,transparent)}
.hs-section{margin:18px 0 6px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ui-text-tertiary)}
.hs-timeline{display:flex;flex-direction:column;border-left:1px solid var(--ui-stroke-tertiary);margin-left:6px}
.hs-ev{position:relative;padding:4px 0 6px 14px;font-size:12px}
.hs-ev::before{content:'';position:absolute;left:-4px;top:9px;width:7px;height:7px;border-radius:999px;background:var(--ui-text-quaternary)}
.hs-ev[data-kind=local]::before{background:${SPARK_GREEN}}
.hs-ev[data-via=failover]::before{background:var(--ui-orange,#df6500)}
.hs-ev small{display:block;color:var(--ui-text-tertiary);font-size:11px}
`


// Platform marks (16x16), drawn here because a disk plugin may import only the SDK and React.
// Vendor first, then the OS when it adds something (an Apple box is macOS already).
function Mark({ kind, x = 0, y = 0, size = 16, title }) {
  const g = (children) => jsxs('svg', { x, y, width: size, height: size, viewBox: '0 0 16 16', role: 'img', 'aria-label': title || kind, className: 'hs-mark', children: [
    title && jsx('title', { children: title }), ...children] })
  const label = (fill, text, fg = '#fff', fs = 5.6) => g([
    jsx('rect', { x: 0.5, y: 2.5, width: 15, height: 11, rx: 2.5, fill }),
    jsx('text', { x: 8, y: 10, textAnchor: 'middle', style: { fill: fg, fontSize: fs, fontWeight: 800, fontFamily: 'system-ui,sans-serif', letterSpacing: '-0.02em' }, children: text })])
  switch (kind) {
    case 'nvidia': return g([
      jsx('rect', { x: 0.5, y: 0.5, width: 15, height: 15, rx: 3, fill: SPARK_GREEN }),
      jsx('path', { d: 'M3 8.2c2.2-3.3 6.8-3.6 10-.2-3.2 3.4-7.8 3.1-10 .2z', fill: 'none', stroke: '#000', strokeWidth: 1.3 }),
      jsx('circle', { cx: 8.2, cy: 8.1, r: 1.6, fill: '#000' })])
    case 'apple': return g([
      jsx('path', { d: 'M8 4.6c1.2-.9 3.4-.9 4.4.8 1 1.7.6 4.6-.9 6.6-.7.9-1.4 1.6-2.3 1.4-.6-.1-.8-.4-1.2-.4s-.6.3-1.2.4c-.9.2-1.6-.5-2.3-1.4C3 10 2.6 7.1 3.6 5.4c1-1.7 3.2-1.7 4.4-.8z', fill: 'var(--ui-text-primary)' }),
      jsx('path', { d: 'M8.4 4c0-1.3.9-2.3 2.1-2.5.1 1.3-.8 2.4-2.1 2.5z', fill: 'var(--ui-text-primary)' })])
    case 'amd': return label('#ED1C24', 'AMD')
    case 'intel': return label('#0071C5', 'intel', '#fff', 5.2)
    case 'windows': return g([
      jsx('rect', { x: 1.5, y: 1.5, width: 6, height: 6, fill: '#00A4EF' }), jsx('rect', { x: 8.5, y: 1.5, width: 6, height: 6, fill: '#00A4EF' }),
      jsx('rect', { x: 1.5, y: 8.5, width: 6, height: 6, fill: '#00A4EF' }), jsx('rect', { x: 8.5, y: 8.5, width: 6, height: 6, fill: '#00A4EF' })])
    case 'linux': return g([
      jsx('ellipse', { cx: 8, cy: 9.2, rx: 4.6, ry: 5.8, fill: 'var(--ui-text-primary)' }),
      jsx('ellipse', { cx: 8, cy: 10.6, rx: 2.8, ry: 3.9, fill: 'var(--ui-bg-elevated,#26262b)' }),
      jsx('circle', { cx: 6.6, cy: 5.6, r: 0.8, fill: 'var(--ui-bg-elevated,#26262b)' }), jsx('circle', { cx: 9.4, cy: 5.6, r: 0.8, fill: 'var(--ui-bg-elevated,#26262b)' }),
      jsx('path', { d: 'M6.8 7l1.2.9 1.2-.9z', fill: '#F5A623' }),
      jsx('ellipse', { cx: 5.6, cy: 15, rx: 1.8, ry: 0.8, fill: '#F5A623' }), jsx('ellipse', { cx: 10.4, cy: 15, rx: 1.8, ry: 0.8, fill: '#F5A623' })])
    default: return null
  }
}

const VENDOR_TITLE = { nvidia: 'NVIDIA', apple: 'Apple silicon', amd: 'AMD', intel: 'Intel' }
const OS_TITLE = { linux: 'Linux', macos: 'macOS', windows: 'Windows' }

function marksFor(n) {
  const p = n.platform || {}
  const out = []
  if (VENDOR_TITLE[p.vendor]) out.push([p.vendor, VENDOR_TITLE[p.vendor] + (p.guessed ? ' (guessed from the name)' : '')])
  if (p.os && OS_TITLE[p.os] && !(p.os === 'macos' && p.vendor === 'apple')) out.push([p.os, OS_TITLE[p.os]])
  return out
}

function Marks({ n, size = 14 }) {
  return jsx('span', { className: 'hs-marks', children: marksFor(n).map(([k, t]) =>
    jsx('svg', { width: size, height: size, viewBox: '0 0 16 16', children: jsx(Mark, { kind: k, title: t }) }, k)) })
}

function speed(n) {
  const p = n.perf || {}
  return p.tps ? `${p.tps >= 100 ? Math.round(p.tps) : p.tps} tok/s` : ''
}

// The theme link toggles: on the DGX Spark theme it offers the theme the user had before (kept in
// the plugin's own storage), else Desktop's default.
const SPARK_THEME = 'dgx-spark'
const DEFAULT_THEME = 'nous'

function ThemeLink({ ctx }) {
  const { themeName, setTheme } = useTheme()
  const on = themeName === SPARK_THEME
  const back = () => {
    let prev = DEFAULT_THEME
    try { prev = ctx.storage.get('themeBefore', DEFAULT_THEME) || DEFAULT_THEME } catch (err) { /* storage unavailable */ }
    setTheme(prev === SPARK_THEME ? DEFAULT_THEME : prev)
  }
  const go = () => {
    try { ctx.storage.set('themeBefore', themeName) } catch (err) { /* storage unavailable */ }
    setTheme(SPARK_THEME)
  }
  return jsx('button', { type: 'button', className: 'hs-link', onClick: on ? back : go,
    title: on ? 'Switch back to your previous theme' : 'Black and NVIDIA green',
    children: on ? 'Default theme' : 'DGX Spark theme' })
}

function ago(iso) {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 60 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
}

function routeLine(s) {
  const a = s.applied || {}
  if (a.kind === 'local') return ['Routed to ', a.node_name, ` · ${a.model || ''}`]
  if (a.kind === 'cloud') return ['Routed to cloud ', `${a.provider}/${a.model}`, a.via === 'failover' ? ' · failover' : '']
  const p = s.primary || {}
  return ['Not routed by Local Fleet · Hermes uses ', p.provider || 'its own primary', p.default ? ` · ${p.default}` : '']
}

function chip(s, failed) {
  if (failed) return { tone: 'bad', text: 'fleet · unreachable' }
  if (!s) return { tone: '', text: 'fleet' }
  if (!s.nodes || !s.nodes.length) return { tone: '', text: 'fleet · no boxes' }
  const a = s.applied || {}
  if (s.down) return { tone: 'bad', text: 'fleet · all down' }
  if (a.kind === 'local') return { tone: 'spark', text: `fleet · ${a.node_name}` }
  if (a.kind === 'cloud') return { tone: a.via === 'failover' ? 'warn' : '', text: 'fleet · cloud' }
  return { tone: '', text: `fleet · ${s.healthy}/${s.nodes.filter(n => n.enabled !== false).length} up` }
}

function NodeRow({ node, active, freest, want, s }) {
  const h = node.last_health || {}
  const off = node.enabled === false
  const load = typeof h.load_proxy === 'number' ? h.load_proxy : null
  const tier = s ? tierOf(node, s) : 0
  const missing = s ? skipped(node, s) : (want && h.status && h.status !== 'down' && !(h.models || []).includes(want))
  const tone = off || missing ? '' : h.status === 'ok' ? 'ok' : h.status === 'degraded' ? 'warn' : h.status === 'down' ? 'bad' : ''
  let sub
  if (off) sub = 'disabled'
  else if (h.status === 'down') sub = h.detail || 'down'
  else if (!h.status) sub = 'not probed yet'
  else if (missing) sub = `skipped · has none of your models`
  else if (tier > 0) sub = `fallback · ${s.model_tiers[tier]}${(node.perf || {}).model === s.model_tiers[tier] && speed(node) ? ' · ' + speed(node) : ''}`
  else {
    const bits = [load === null ? 'load unknown' : load < 0.05 ? 'idle' : `${Math.round(load * 100)}% busy`]
    if (speed(node)) bits.push(speed(node))
    if (h.free_vram_approx) bits.push(`${Math.round(h.free_vram_approx / 1e9)} GB free`)
    sub = bits.join(' · ')
  }
  return jsxs('div', { className: 'hs-row', 'data-active': active, 'data-skipped': Boolean(off || missing || h.status === 'down'), children: [
    jsx('span', { className: 'hs-dot', 'data-tone': tone }),
    jsxs('div', { className: 'hs-name', children: [
      jsx(Marks, { n: node, size: 13 }),
      jsx('span', { children: node.name }),
      active && jsx('em', { className: 'hs-badge', 'data-kind': 'active', style: { fontStyle: 'normal' }, children: 'active' }),
      !active && freest && jsx('em', { className: 'hs-badge', 'data-kind': 'freest', style: { fontStyle: 'normal' }, children: 'least busy' })
    ] }),
    jsx('span', { className: 'hs-lat', children: h.latency_ms != null && !off ? `${h.latency_ms} ms` : '' }),
    jsxs('div', { className: 'hs-sub', children: [
      load !== null && !off && !missing && h.status !== 'down' && jsx('span', { className: 'hs-meter', 'data-busy': load > 0.75,
        children: jsx('i', { style: { width: `${Math.max(3, load * 100)}%` } }) }),
      jsx('span', { className: 'hs-sub-text', children: `${node.kind} · ${sub}` })
    ] })
  ] })
}

function Panel({ ctx, status }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')
  const run = async (label, path, body) => {
    setBusy(label)
    try {
      const next = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 150000 })
      qc.setQueryData(KEY, next)
      const d = next.decision || {}
      host.notify({ kind: d.warning ? 'warning' : 'success', title: 'Local Fleet',
        message: d.warning || d.reason || 'done', detail: d.applied ? `${d.warm && d.warm.warmed ? d.warm.detail + ' first. ' : ''}Applies from the next message.` : undefined })
    } catch (err) {
      host.notifyError(err, 'Local Fleet request failed')
    } finally {
      setBusy('')
    }
  }
  const s = status || {}
  const activeId = (s.applied || {}).node_id
  const freestId = (s.decision || s.last_decision || {}).freest_node_id
  const [lead, strong, tail] = routeLine(s)
  return jsxs('div', { className: 'hs-panel', children: [
    jsxs('div', { className: 'hs-head', children: [
      jsx('span', { className: 'hs-title', children: 'Local Fleet' }),
      jsx('span', { className: 'hs-mode-tag', children: (s.nodes || []).length ? `${s.healthy ?? 0}/${s.nodes.filter(n => n.enabled !== false).length} boxes up` : '' })
    ] }),
    jsxs('div', { className: 'hs-route', title: `${lead}${strong}${tail}`, children: [lead, jsx('b', { children: strong }), tail] }),
    jsx('div', { className: 'hs-list', children: (s.nodes || []).length
      ? s.nodes.map(n => jsx(NodeRow, { node: n, active: n.id === activeId, freest: n.id === freestId, want: s.local_model, s }, n.id))
      : jsx('div', { className: 'hs-error', children: 'No boxes yet. In a terminal: hermes fleet add --name gx10 --url http://<host>:11434/v1' }) }),
    jsxs('div', { className: 'hs-controls', children: [
      jsx('div', { className: 'hs-seg', role: 'radiogroup', 'aria-label': 'Routing mode', children: MODES.map(([m, label]) =>
        jsx('button', { key: m, type: 'button', role: 'radio', 'aria-checked': s.mode === m, disabled: Boolean(busy), title: m,
          onClick: () => { if (s.mode !== m) { haptic('tap'); run('mode', '/mode', { mode: m }) } }, children: label })) }),
      jsxs('div', { className: 'hs-actions', children: [
        jsx(Button, { size: 'sm', disabled: Boolean(busy), title: AUTO_PICK_TIP, onClick: () => run('use', '/use', { node: 'best' }),
          children: busy === 'use' ? 'Switching…' : 'Auto-pick box' }),
        jsx(Button, { size: 'sm', variant: 'outline', disabled: Boolean(busy), onClick: () => run('probe', '/probe'),
          children: busy === 'probe' ? 'Probing…' : 'Probe now' })
      ] })
    ] }),
    jsxs('div', { className: 'hs-foot', children: [
      jsx('button', { type: 'button', className: 'hs-link', onClick: () => host.navigate(PAGE_PATH), children: 'Open fleet map' }),
      jsx('span', { children: s.last_probe_at ? `probed ${ago(s.last_probe_at)}` : '' }),
      jsx(ThemeLink, { ctx })
    ] })
  ] })
}

function Unreachable({ error, onRetry }) {
  return jsxs('div', { className: 'hs-panel', children: [
    jsx('div', { className: 'hs-head', children: jsx('span', { className: 'hs-title', children: 'Local Fleet' }) }),
    jsxs('div', { className: 'hs-error', children: [
      'The local-fleet backend did not answer. Enable the plugin on the Hermes this app is connected to and restart its dashboard.',
      jsx('code', { children: String((error && error.message) || error || 'unknown error') })
    ] }),
    jsx('div', { className: 'hs-controls', children: jsx(Button, { size: 'sm', onClick: onRetry, children: 'Retry' }) })
  ] })
}

function Chip({ ctx }) {
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: KEY, queryFn: () => ctx.rest('/status'), refetchInterval: 15000, retry: 1, staleTime: 5000 })
  if (q.data) LAST = q.data
  const failed = q.isError && !q.data
  const c = chip(q.data, failed)
  return jsxs(Popover, { open, onOpenChange: setOpen, children: [
    jsx(PopoverTrigger, { asChild: true, children: jsx(Button, {
      variant: 'ghost', size: 'micro', 'aria-label': `Local Fleet: ${c.text}`, className: 'text-[0.6875rem]',
      children: jsxs('span', { className: 'hs-chip', children: [jsx('span', { className: 'hs-dot', 'data-tone': c.tone }), c.text] })
    }) }),
    jsx(PopoverContent, { side: 'top', align: 'end', className: 'hs-pop', 'aria-label': 'Local Fleet', children: failed
      ? jsx(Unreachable, { error: q.error, onRetry: () => q.refetch() })
      : jsx(Panel, { ctx, status: q.data }) })
  ] })
}

// ---------------------------------------------------------------------------
// Fleet page (sidebar "Local Fleet"): a hardware map of where Hermes sends its requests.
// SVG only (the plugin import whitelist allows no WebGL libraries); isometric server boxes.

const W = 960
const H = 470
const HUB = { x: 165, y: 255 }
const CLOUD = { x: 520, y: 70 }

function nodeTone(n) {
  const h = n.last_health || {}
  if (n.enabled === false) return 'off'
  return h.status === 'ok' ? 'ok' : h.status === 'degraded' ? 'warn' : h.status === 'down' ? 'bad' : 'off'
}

// The tier a healthy box serves: 0 = the main model, 1+ = a fallback model, -1 = none of them.
function tierOf(n, s) {
  const tiers = s.model_tiers && s.model_tiers.length ? s.model_tiers : (s.local_model ? [s.local_model] : [])
  if (!tiers.length) return 0
  const models = (n.last_health || {}).models || []
  return tiers.findIndex(m => models.includes(m))
}

// Healthy but not a candidate: it has none of the local models routes use.
function skipped(n, s) {
  const h = n.last_health || {}
  return Boolean(h.status && h.status !== 'down' && tierOf(n, s) < 0)
}

const TONE_FILL = { ok: 'var(--ui-green,#3fb950)', warn: 'var(--ui-orange,#df6500)', bad: 'var(--ui-red,#e5484d)', off: 'var(--ui-text-quaternary)' }

function nodePositions(count) {
  const cols = count > 4 ? 2 : 1
  const rows = Math.ceil(count / cols)
  const top = 150
  const span = H - top - 40
  const step = rows > 1 ? span / (rows - 1) : 0
  return Array.from({ length: count }, (_, i) => {
    const col = cols === 2 ? i % 2 : 0
    const row = cols === 2 ? Math.floor(i / 2) : i
    return { x: cols === 2 ? 640 + col * 190 : 720, y: rows > 1 ? top + row * step : top + span / 2 }
  })
}

// An isometric server: top, left and right faces, rack lines and LEDs on the front.
function IsoServer({ x, y, tone, active, load }) {
  const w = 46
  const d = 26
  const h = 40
  const top = `${x},${y - h} ${x + w},${y - h + d / 2} ${x},${y - h + d} ${x - w},${y - h + d / 2}`
  const left = `${x - w},${y - h + d / 2} ${x},${y - h + d} ${x},${y + d} ${x - w},${y + d / 2}`
  const right = `${x},${y - h + d} ${x + w},${y - h + d / 2} ${x + w},${y + d / 2} ${x},${y + d}`
  const dim = tone === 'off' || tone === 'bad'
  const led = active ? SPARK_GREEN : TONE_FILL[tone]
  const racks = [0.3, 0.55, 0.8].map(f => {
    const yy = y - h + d + f * h
    return jsx('line', { x1: x - w + 4, y1: yy - d / 2 + 2, x2: x - 4, y2: yy, stroke: 'currentColor', strokeOpacity: 0.18 }, f)
  })
  const leds = [0, 1, 2].map(i => jsx('circle', {
    className: dim ? undefined : 'hs-led', cx: x + 10 + i * 9, cy: y - h + d + 8 - i * 4.5 + 10, r: 2.2, fill: led,
    opacity: dim ? 0.5 : 1
  }, i))
  const meterLen = 30
  return jsxs('g', { style: { color: 'var(--ui-text-primary)' }, opacity: tone === 'off' ? 0.45 : 1, children: [
    active && jsx('ellipse', { cx: x, cy: y + d / 2 + 6, rx: w + 16, ry: d, fill: SPARK_GREEN, opacity: 0.12 }),
    jsx('polygon', { points: left, fill: 'var(--ui-bg-tertiary,#1b1b1f)', stroke: 'var(--ui-stroke-secondary)' }),
    jsx('polygon', { points: right, fill: 'var(--ui-bg-secondary,#141417)', stroke: 'var(--ui-stroke-secondary)' }),
    jsx('polygon', { points: top, fill: active ? `color-mix(in srgb, ${SPARK_GREEN} 30%, var(--ui-bg-elevated,#26262b))` : 'var(--ui-bg-elevated,#26262b)', stroke: active ? SPARK_GREEN : 'var(--ui-stroke-secondary)' }),
    ...racks,
    ...leds,
    // load meter along the right face's bottom edge
    typeof load === 'number' && jsx('line', { x1: x + 6, y1: y + d - 6, x2: x + 6 + meterLen, y2: y + d - 6 - meterLen / 2 * (d / w), stroke: 'currentColor', strokeOpacity: 0.15, strokeWidth: 3, strokeLinecap: 'round' }),
    typeof load === 'number' && jsx('line', { x1: x + 6, y1: y + d - 6, x2: x + 6 + meterLen * Math.max(0.05, load), y2: y + d - 6 - meterLen * Math.max(0.05, load) / 2 * (d / w), stroke: load > 0.75 ? 'var(--ui-orange,#df6500)' : SPARK_GREEN, strokeWidth: 3, strokeLinecap: 'round' })
  ] })
}

function Hub({ s }) {
  const p = s.primary || {}
  const a = s.applied || {}
  const model = a.model || p.default || ''
  return jsxs('g', { children: [
    jsx('circle', { cx: HUB.x, cy: HUB.y, r: 46, fill: 'none', stroke: 'var(--ui-stroke-tertiary)' }),
    jsx('circle', { cx: HUB.x, cy: HUB.y, r: 34, fill: 'var(--ui-bg-elevated,#26262b)', stroke: SPARK_GREEN, strokeWidth: 1.5 }),
    jsx('text', { x: HUB.x, y: HUB.y + 8, textAnchor: 'middle', style: { fontSize: 24, fontWeight: 700, fill: SPARK_GREEN }, children: 'H' }),
    jsx('text', { x: HUB.x, y: HUB.y + 70, textAnchor: 'middle', style: { fontWeight: 600 }, children: 'Hermes' }),
    jsx('text', { className: 't2', x: HUB.x, y: HUB.y + 86, textAnchor: 'middle', children: model.length > 30 ? `${model.slice(0, 29)}…` : model }),
    jsx('text', { className: 't3', x: HUB.x, y: HUB.y - 60, textAnchor: 'middle', children: 'AGENT' })
  ] })
}

function Cloud({ s, live }) {
  const chain = (s.fallback_chain || []).filter(e => e.provider && e.provider !== 'custom')
  const last = chain[chain.length - 1]
  const label = live ? `${(s.applied || {}).provider}/${(s.applied || {}).model}` : last ? `${last.provider}/${last.model}` : 'no cloud backup'
  const { x, y } = CLOUD
  return jsxs('g', { opacity: live ? 1 : 0.7, children: [
    jsx('path', { d: `M${x - 44} ${y + 14} a18 18 0 0 1 6 -34 a26 26 0 0 1 48 -6 a20 20 0 0 1 30 18 a16 16 0 0 1 -4 22 z`,
      fill: 'var(--ui-bg-elevated,#26262b)', stroke: live ? 'var(--ui-orange,#df6500)' : 'var(--ui-stroke-secondary)', strokeWidth: live ? 1.8 : 1 }),
    jsx('text', { x: x + 66, y: y - 2, children: 'Cloud backup' }),
    jsx('text', { className: 't2', x: x + 66, y: y + 13, children: label })
  ] })
}

function wirePath(a, b) {
  const mx = (a.x + b.x) / 2
  return `M${a.x} ${a.y} C${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`
}

function Packets({ id, color }) {
  return [0, 0.6, 1.2].map(delay => jsx('circle', { r: 3.2, fill: color, children:
    jsx('animateMotion', { dur: '1.8s', begin: `${delay}s`, repeatCount: 'indefinite', children: jsx('mpath', { href: `#${id}` }) }) }, delay))
}

function liveCalls(s, n) {
  return (((s.traffic || {}).boxes || {})[n.id] || {}).live || 0
}

function recentDelegation(s, n) {
  return (s.delegations || []).some(d => d.label === n.name && Date.now() - Date.parse(d.at) < 120000)
}

// Amounts in the user's locale (symbol position, decimal comma, grouping) for the configured ISO code.
function money(s, v) {
  const code = /^[A-Z]{3}$/.test(s.currency || '') ? s.currency : 'USD'
  try {
    // Each currency keeps its own minor units (yen has none); large sums drop them.
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: code, ...(v >= 100 ? { maximumFractionDigits: 0 } : {}) }).format(v)
  } catch (err) {
    return `${v.toFixed(2)} ${code}`
  }
}

function FleetMap({ s }) {
  const nodes = s.nodes || []
  const pos = nodePositions(nodes.length)
  const a = s.applied || {}
  const cloudLive = a.kind === 'cloud'
  const reduced = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const hubEdge = { x: HUB.x + 46, y: HUB.y }
  const cloudPath = `M${HUB.x} ${HUB.y - 46} C${HUB.x} ${CLOUD.y + 10}, ${CLOUD.x - 140} ${CLOUD.y}, ${CLOUD.x - 46} ${CLOUD.y}`
  return jsx('div', { className: 'hs-map', children: jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Local Fleet map', children: [
    jsx('path', { id: 'hs-wire-cloud', className: 'hs-wire', 'data-cloud': true, 'data-live': cloudLive, d: cloudPath }),
    cloudLive && !reduced && Packets({ id: 'hs-wire-cloud', color: 'var(--ui-orange,#df6500)' }),
    ...nodes.map((n, i) => {
      const active = a.kind === 'local' && a.node_id === n.id
      const tone = skipped(n, s) ? 'off' : nodeTone(n)
      const end = { x: pos[i].x - 50, y: pos[i].y + 4 }
      const id = `hs-wire-${n.id}`
      const busy = !active && liveCalls(s, n) > 0
      return jsxs('g', { children: [
        jsx('path', { id, className: 'hs-wire', 'data-live': active, 'data-traffic': busy, 'data-off': !busy && (tone === 'off' || tone === 'bad'), d: wirePath(hubEdge, end) }),
        (active || busy) && !reduced && Packets({ id, color: active ? SPARK_GREEN : '#6ee7ff' })
      ] }, `w-${n.id}`)
    }),
    jsx(Hub, { s }),
    jsx(Cloud, { s, live: cloudLive }),
    ...nodes.map((n, i) => {
      const h = n.last_health || {}
      const active = a.kind === 'local' && a.node_id === n.id
      const tone = skipped(n, s) ? 'off' : nodeTone(n)
      const { x, y } = pos[i]
      const missing = skipped(n, s)
      const tier = tierOf(n, s)
      const res = (h.resident || []).filter(m => !/embed/i.test(m))
      const resident = res.length ? res[0] + (res.length > 1 ? ` +${res.length - 1}` : '') : ''
      const line2 = n.enabled === false ? 'disabled' : h.status === 'down' ? (h.detail || 'down') : missing ? `none of ${(s.model_tiers || [s.local_model]).join(', ')}`
        : tier > 0 ? [`fallback · ${s.model_tiers[tier]}`, (n.perf || {}).model === s.model_tiers[tier] ? speed(n) : null].filter(Boolean).join(' · ')
        : [speed(n) || (h.latency_ms != null ? `${h.latency_ms} ms` : null), typeof h.load_proxy === 'number' ? (h.load_proxy < 0.05 ? 'idle' : `${Math.round(h.load_proxy * 100)}% busy`) : null,
           h.free_vram_approx ? `${Math.round(h.free_vram_approx / 1e9)} GB free` : null].filter(Boolean).join(' · ')
      return jsxs('g', { children: [
        jsx(IsoServer, { x, y, tone, active, load: h.load_proxy }),
        jsx('circle', { cx: x + 62, cy: y - 22, r: 3.5, fill: active ? SPARK_GREEN : TONE_FILL[tone] }),
        ...marksFor(n).map(([k, t], j) => jsx(Mark, { kind: k, title: t, x: x + 70 + j * 19, y: y - 31, size: 16 }, k)),
        jsx('text', { x: x + 72 + marksFor(n).length * 19, y: y - 18, style: { fontWeight: 600 }, children: n.name + (active ? '  ← routed' : '') }),
        jsx('text', { className: 't2', x: x + 70, y: y - 3, children: line2 }),
        resident && jsx('text', { className: 't2', x: x + 70, y: y + 11, children: `in memory: ${resident.length > 26 ? resident.slice(0, 25) + '…' : resident}` }),
        liveCalls(s, n) > 0 && jsx('text', { className: 't2', x: x + 70, y: y + 25, style: { fill: '#6ee7ff' }, children: `● live · ${liveCalls(s, n)} call${liveCalls(s, n) === 1 ? '' : 's'}${recentDelegation(s, n) ? ' · subagents' : ''}` })
      ] }, n.id)
    })
  ] }) })
}

function Sparkline({ points }) {
  const pts = (points || []).filter(p => p.lat != null)
  if (pts.length < 2) return jsx('svg', { className: 'hs-spark', viewBox: '0 0 200 38', children: jsx('text', { className: 't2', x: 0, y: 22, style: { fill: 'var(--ui-text-quaternary)', fontSize: 11 }, children: 'collecting…' }) })
  const max = Math.max(...pts.map(p => p.lat), 10)
  const xs = i => (i / (pts.length - 1)) * 200
  const lat = pts.map((p, i) => `${xs(i).toFixed(1)},${(34 - (p.lat / max) * 30).toFixed(1)}`).join(' ')
  const load = pts.map((p, i) => `${xs(i).toFixed(1)},${(36 - (p.load || 0) * 32).toFixed(1)}`).join(' ')
  return jsxs('svg', { className: 'hs-spark', viewBox: '0 0 200 38', preserveAspectRatio: 'none', children: [
    jsx('polygon', { points: `0,38 ${load} 200,38`, fill: SPARK_GREEN, opacity: 0.18 }),
    jsx('polyline', { points: lat, fill: 'none', stroke: 'var(--ui-text-secondary)', strokeWidth: 1.2, vectorEffect: 'non-scaling-stroke' })
  ] })
}

function NodeCard({ n, s }) {
  const h = n.last_health || {}
  const active = (s.applied || {}).kind === 'local' && (s.applied || {}).node_id === n.id
  const want = s.local_model
  const models = (h.models || n.models || []).filter(m => !/embed/i.test(m))
  return jsxs('div', { className: 'hs-card', 'data-active': active, children: [
    jsxs('div', { className: 'hs-card-head', children: [
      jsx('span', { className: 'hs-dot', 'data-tone': active ? 'spark' : { ok: 'ok', warn: 'warn', bad: 'bad' }[nodeTone(n)] || '' }),
      jsx(Marks, { n, size: 15 }),
      jsx('span', { children: n.name }),
      jsx('span', { className: 'hs-lat', children: h.latency_ms != null ? `${h.latency_ms} ms` : '' })
    ] }),
    jsxs('div', { className: 'hs-card-perf', children: [
      jsx('b', { children: (n.perf || {}).tps ? `${(n.perf || {}).tps}` : '—' }),
      jsx('span', { children: (n.perf || {}).tps ? ` tok/s · ${(n.perf || {}).model}${(n.perf || {}).prompt_tps ? ` · prompt ${(n.perf || {}).prompt_tps} tok/s` : ''} · ${ago((n.perf || {}).at)}`
        : ` tok/s · ${((n.perf_note || {}).skipped) || 'not benched yet'}` })
    ] }),
    (() => {
      const t = ((s.traffic || {}).boxes || {})[n.id]
      return t ? jsx('div', { className: 'hs-card-perf', children: `real traffic: ${t.calls} calls this week${t.tps ? ` · ${t.tps} tok/s effective` : ''}${t.latency_s ? ` · ${t.latency_s}s median` : ''}${t.errors ? ` · ${t.errors} errors` : ''}` }) : null
    })(),
    jsx('div', { className: 'hs-card-sub', title: n.base_url, children: `${n.kind} · ${(n.labels || []).join(', ') || 'no labels'} · ${n.base_url}` }),
    jsx(Sparkline, { points: (s.series || {})[n.id] }),
    jsx('div', { className: 'hs-models', children: models.slice(0, 8).map(m => jsx('span', {
      'data-want': m === want, 'data-fallback': (s.model_tiers || []).slice(1).includes(m),
      title: m === want ? `${m} (your main model)` : (s.model_tiers || []).includes(m) ? `${m} (fallback model)` : m, children: m }, m)) })
  ] })
}

function Timeline({ history }) {
  const items = (history || []).slice().reverse().slice(0, 12)
  if (!items.length) return jsx('div', { className: 'hs-page-hint', children: 'No routing changes yet. Auto-pick box, a mode change or a failover will appear here.' })
  return jsx('div', { className: 'hs-timeline', children: items.map((e, i) => jsxs('div', { className: 'hs-ev', 'data-kind': e.kind, 'data-via': e.via || '', children: [
    e.kind === 'local' ? `→ ${e.node} · ${e.model}` : `→ cloud · ${e.model}`,
    jsx('small', { children: `${ago(e.at)} · ${e.reason}` })
  ] }, `${e.at}-${i}`)) })
}

function FleetPage({ ctx }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')
  const q = useQuery({ queryKey: KEY, queryFn: () => ctx.rest('/status'), refetchInterval: 10000, retry: 1, staleTime: 3000 })
  const run = async (label, path, body) => {
    setBusy(label)
    try {
      const next = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 150000 })
      qc.setQueryData(KEY, next)
      const d = next.decision || {}
      host.notify({ kind: d.warning ? 'warning' : 'success', title: 'Local Fleet', message: d.warning || d.reason || 'done',
        detail: d.applied ? 'Applies from the next message.' : undefined })
    } catch (err) {
      host.notifyError(err, 'Local Fleet request failed')
    } finally {
      setBusy('')
    }
  }
  if (q.data) LAST = q.data
  if (q.isError && !q.data) return jsx('div', { className: 'hs-page', children: jsx(Unreachable, { error: q.error, onRetry: () => q.refetch() }) })
  const s = q.data || {}
  const nodes = s.nodes || []
  const enabled = nodes.filter(n => n.enabled !== false)
  const a = s.applied || {}
  const [lead, strong, tail] = routeLine(s)
  return jsxs('div', { className: 'hs-page', children: [
    jsxs('div', { className: 'hs-page-head', children: [
      jsxs('h1', { children: ['Local ', jsx('span', { children: 'Fleet' })] }),
      jsx('div', { className: 'hs-page-hint', children: `${lead}${strong}${tail}` })
    ] }),
    jsxs('div', { className: 'hs-stats', children: [
      jsxs('div', { className: 'hs-stat', children: [jsx('b', { children: nodes.length }), jsx('span', { children: 'Boxes' })] }),
      jsxs('div', { className: 'hs-stat', children: [jsx('b', { children: `${s.healthy ?? '…'}/${enabled.length}` }), jsx('span', { children: 'Healthy' })] }),
      jsxs('div', { className: 'hs-stat', children: [jsx('b', { style: a.kind === 'local' ? { color: SPARK_GREEN } : undefined, children: a.kind === 'local' ? a.node_name : a.kind === 'cloud' ? 'cloud' : '—' }), jsx('span', { children: 'Routed to' })] }),
      jsxs('div', { className: 'hs-stat', children: [jsx('b', { children: s.mode || '…' }), jsx('span', { children: 'Mode' })] }),
      jsxs('div', { className: 'hs-stat', children: [jsx('b', { children: (s.traffic || {}).local_share != null ? `${Math.round(s.traffic.local_share * 100)}%` : '—' }), jsx('span', { children: 'Tokens run locally (7 d)' })] }),
      jsxs('div', { className: 'hs-stat', title: (s.traffic || {}).saved == null ? 'Set a cloud price: hermes fleet price <in> <out> --currency GBP' : 'Local tokens at your cloud price', children: [
        jsx('b', { style: (s.traffic || {}).saved ? { color: SPARK_GREEN } : undefined, children: (s.traffic || {}).saved != null ? money(s, s.traffic.saved) : '—' }),
        jsx('span', { children: 'Cloud spend avoided (7 d)' })] })
    ] }),
    jsxs('div', { className: 'hs-toolbar', children: [
      jsx('div', { className: 'hs-seg', role: 'radiogroup', 'aria-label': 'Routing mode', children: MODES.map(([m, label]) =>
        jsx('button', { key: m, type: 'button', role: 'radio', 'aria-checked': s.mode === m, disabled: Boolean(busy), title: m,
          onClick: () => { if (s.mode !== m) { haptic('tap'); run('mode', '/mode', { mode: m }) } }, children: label })) }),
      jsx(Button, { size: 'sm', disabled: Boolean(busy), title: AUTO_PICK_TIP, onClick: () => run('use', '/use', { node: 'best' }), children: busy === 'use' ? 'Switching…' : 'Auto-pick box' }),
      jsx(Button, { size: 'sm', variant: 'outline', disabled: Boolean(busy), onClick: () => run('probe', '/probe'), children: busy === 'probe' ? 'Probing…' : 'Probe now' }),
      jsx(Button, { size: 'sm', variant: 'outline', disabled: Boolean(busy), title: 'Short generation on each box that has a model in memory',
        onClick: () => run('bench', '/bench'), children: busy === 'bench' ? 'Benchmarking…' : 'Benchmark' }),
      jsxs('button', { type: 'button', className: 'hs-toggle', role: 'switch', 'aria-checked': s.delegation_backend === 'fleet', disabled: Boolean(busy),
        title: 'delegate_task subagents run on the fleet, spread across boxes (from the next session)',
        onClick: () => run('delegate', '/delegate', { on: s.delegation_backend !== 'fleet' }), children: [jsx('i', {}), 'Subagents on fleet'] }),
      jsxs('button', { type: 'button', className: 'hs-toggle', role: 'switch', 'aria-checked': Boolean(s.aux), disabled: Boolean(busy),
        title: s.aux ? `${s.aux.tasks.join(', ')} → ${s.aux.node_name}` : 'Session titles and compression run on the least busy box, with cloud as backup',
        onClick: () => run('aux', '/aux', { on: !s.aux }), children: [jsx('i', {}), 'Side tasks on fleet'] }),
      jsx('span', { className: 'hs-page-hint', style: { marginLeft: 'auto' }, children: s.last_probe_at ? `probed ${ago(s.last_probe_at)} · refreshes every 10 s` : '' })
    ] }),
    jsx(FleetMap, { s }),
    jsx('div', { className: 'hs-cards', children: nodes.map(n => jsx(NodeCard, { n, s }, n.id)) }),
    jsx('div', { className: 'hs-section', children: 'Routing history' }),
    jsx(Timeline, { history: s.history })
  ] })
}

const dgxSparkTheme = {
  name: 'dgx-spark',
  label: 'DGX Spark',
  description: 'Black and NVIDIA green, from local-fleet',
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
  name: 'Local Fleet',
  description: 'Which of your inference boxes Hermes is routed to, its health, and one-click switching.',
  defaultEnabled: true,
  register(ctx) {
    const style = document.createElement('style')
    style.textContent = CSS
    document.head.append(style)
    ctx.onDispose(() => style.remove())
    const post = async (path, body, label) => {
      try {
        const next = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 150000 })
        const d = next.decision || {}
        host.notify({ kind: d.warning ? 'warning' : 'info', title: label, message: d.warning || d.reason || 'done' })
      } catch (err) {
        host.notifyError(err, `${label} failed`)
      }
    }
    const openPage = () => host.navigate(PAGE_PATH)
    ctx.register({ id: 'page', area: ROUTES_AREA, data: { path: PAGE_PATH }, render: () => jsx(FleetPage, { ctx }) })
    ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: PAGE_PATH, label: 'Local Fleet', codicon: 'server' } })
    ctx.register({ id: 'palette-open', area: PALETTE_AREA,
      data: { id: 'fleet-open', label: 'Fleet: open the fleet map', keywords: ['spark', 'fleet', 'hardware', 'map'], run: openPage } })
    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 125, render: () => jsx(Chip, { ctx }) })
    // Model menu: which box serves each model, with its platform mark and speed.
    ctx.register({ id: 'model-rows', area: MODEL_MENU_ROW_AREA, data: { decorate: ({ model }) => {
      const nodes = ((LAST || {}).nodes || []).filter(n => n.enabled !== false && ((n.last_health || {}).models || n.models || []).includes(model))
      if (!nodes.length) return null
      const best = nodes.slice().sort((x, y) => ((y.perf || {}).tps || 0) - ((x.perf || {}).tps || 0))[0]
      const mark = marksFor(best)[0]
      const sp = (best.perf || {}).model === model ? speed(best) : ''
      return { icon: mark ? jsx('svg', { width: 16, height: 16, viewBox: '0 0 16 16', children: jsx(Mark, { kind: mark[0], title: mark[1] }) }) : undefined,
        badge: nodes.length > 1 ? `${nodes.length} boxes${sp ? ` · ${best.name} ${sp}` : ''}` : `${best.name}${sp ? ` · ${sp}` : ''}` }
    } } })
    // Model pill: name the box when Hermes is routed to one by the fleet.
    ctx.register({ id: 'model-pill', area: COMPOSER_AREAS.modelPill, data: { label: ({ model }) => {
      const a = (LAST || {}).applied || {}
      return a.kind === 'local' && a.model && model && (model === a.model || model.endsWith(a.model)) ? `${model} @ ${a.node_name}` : null
    } } })
    ctx.register({ id: 'theme', area: THEMES_AREA, data: dgxSparkTheme })
    ctx.register({ id: 'palette-freest', area: PALETTE_AREA,
      data: { id: 'fleet-use-freest', label: 'Fleet: switch to the least busy box', keywords: ['spark', 'fleet', 'ollama', 'gpu', 'auto', 'pick'],
        run: () => post('/use', { node: 'best' }, 'Fleet: auto-pick box') } })
    ctx.register({ id: 'palette-probe', area: PALETTE_AREA,
      data: { id: 'fleet-probe', label: 'Fleet: probe the fleet', keywords: ['spark', 'health'],
        run: () => post('/probe', {}, 'Fleet: probe') } })
    for (const [m] of MODES) {
      ctx.register({ id: `palette-mode-${m}`, area: PALETTE_AREA,
        data: { id: `fleet-mode-${m}`, label: `Fleet: mode ${m}`, keywords: ['spark', 'mode', 'routing'],
          run: () => post('/mode', { mode: m }, `Fleet: ${m}`) } })
    }
  }
}
