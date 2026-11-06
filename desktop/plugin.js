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
.hs-pick{cursor:pointer}
.hs-pick:hover polygon{filter:brightness(1.25)}
.hs-roles{font-size:10.5px;font-weight:600}
.hs-roles tspan[data-k=chat]{fill:${SPARK_GREEN}}
.hs-roles tspan[data-k=aux]{fill:#c7a3ff}
.hs-roles tspan[data-k=sub]{fill:#6ee7ff}
.hs-roles tspan[data-k=ex]{fill:var(--ui-orange,#df6500)}
.hs-badge[data-kind=ex]{color:var(--ui-orange,#df6500);border-color:var(--ui-orange,#df6500)}
.hs-card-actions{display:flex;gap:14px;margin-top:8px;font-size:11px}
.hs-card-actions .hs-link:disabled{opacity:.5;cursor:default}
.hs-stat-btn{all:unset;cursor:pointer;border:1px solid var(--ui-stroke-tertiary);border-radius:8px;padding:10px 14px;min-width:0}
.hs-stat-btn:hover{border-color:${SPARK_GREEN}}
.hs-stat-btn b{display:block;font-size:20px;font-weight:600;line-height:26px}
.hs-stat-btn span{font-size:12px;color:var(--ui-text-tertiary)}
.hs-drift{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;padding:10px 14px;border:1px solid var(--ui-orange,#df6500);border-radius:8px;font-size:12px;background:color-mix(in srgb,var(--ui-orange,#df6500) 8%,transparent)}
.hs-drift>div{flex:1;min-width:240px}
.hs-drawer-wrap{position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.35);display:flex;justify-content:flex-end}
.hs-drawer{width:min(620px,92vw);height:100%;overflow-y:auto;background:var(--ui-bg-elevated,#1b1b20);border-left:1px solid var(--ui-stroke-secondary);box-shadow:-20px 0 50px rgba(0,0,0,.4)}
.hs-drawer-head{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--ui-stroke-tertiary);background:inherit;font-size:15px}
.hs-drawer-body{padding:14px 18px 24px;font-size:12.5px;display:flex;flex-direction:column;gap:12px}
.hs-why-route{font-size:18px;font-weight:600;color:${SPARK_GREEN}}
.hs-why-head{display:flex;flex-direction:column;gap:3px}
.hs-why-head small{color:var(--ui-text-tertiary)}
.hs-why-table{width:100%;border-collapse:collapse;font-size:12px}
.hs-why-table th{text-align:left;font-weight:500;color:var(--ui-text-tertiary);padding:4px 6px;border-bottom:1px solid var(--ui-stroke-tertiary)}
.hs-why-table td{padding:6px;border-bottom:1px solid var(--ui-stroke-tertiary);vertical-align:middle}
.hs-why-table tr[data-chosen=true] td{color:${SPARK_GREEN};font-weight:600}
.hs-why-table td[data-stale=true]{color:var(--ui-orange,#df6500)}
.hs-why-table tr[data-out=true] td{color:var(--ui-text-tertiary)}
.hs-why-table tr[data-focus=true] td{background:var(--ui-row-active-background)}
.hs-ready{margin-top:4px}
.hs-why-table .hs-meter{display:inline-block;width:56px;vertical-align:middle}
.hs-rec-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--ui-text-tertiary);margin-bottom:8px}
.hs-rec-legend span::before{content:'';display:inline-block;width:7px;height:7px;border-radius:9px;margin-right:5px;background:var(--ui-text-quaternary)}
.hs-rec-legend span[data-k=route]::before,.hs-ev[data-k=route]::before{background:${SPARK_GREEN}}
.hs-rec-legend span[data-k=served]::before,.hs-ev[data-k=served]::before{background:#6ee7ff}
.hs-rec-legend span[data-k=health]::before,.hs-ev[data-k=health]::before{background:var(--ui-red,#e5484d)}
.hs-rec-legend span[data-k=rehearsal]::before,.hs-ev[data-k=rehearsal]::before,.hs-ev[data-k=maintenance]::before,.hs-ev[data-k=drift]::before{background:var(--ui-orange,#df6500)}
.hs-ev em{font-style:normal;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--ui-text-tertiary)}
.hs-caveat{padding:8px 10px;border-left:3px solid var(--ui-orange,#df6500);color:var(--ui-text-secondary)}
.hs-check{display:grid;grid-template-columns:18px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid var(--ui-stroke-tertiary)}
.hs-check-icon{font-weight:700;text-align:center}
.hs-check[data-level=ok] .hs-check-icon{color:${SPARK_GREEN}}
.hs-check[data-level=warn] .hs-check-icon{color:var(--ui-orange,#df6500)}
.hs-check[data-level=error] .hs-check-icon{color:var(--ui-red,#e5484d)}
.hs-check-body{display:flex;flex-direction:column;gap:4px}
.hs-check-body div{color:var(--ui-text-secondary)}
.hs-check-body code{font-size:11px;padding:4px 6px;border-radius:4px;background:var(--ui-bg-tertiary,#141418);word-break:break-all}
.hs-check-actions{display:flex;gap:8px}
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
.hs-link-live{animation:hs-flow 0.5s linear infinite;filter:drop-shadow(0 0 4px color-mix(in srgb,${SPARK_GREEN} 70%,transparent))}
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
.hs-mem{margin:8px 0 2px}
.hs-card[data-cluster=true]{grid-column:span 2}
@container (max-width:560px){.hs-card[data-cluster=true]{grid-column:auto}}
.hs-cluster-members{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.hs-mem-who{font-size:11px;font-weight:600;margin-top:8px;color:var(--ui-text-secondary)}
.hs-name-btn{all:unset;cursor:pointer;display:inline-flex;align-items:baseline;gap:6px;min-width:0}
.hs-name-btn small{font-size:10.5px;font-weight:400;color:var(--ui-text-quaternary)}
.hs-name-btn i{font-style:normal;font-size:11px;color:var(--ui-text-quaternary);opacity:0;transition:opacity .15s}
.hs-name-btn:hover i,.hs-name-btn:focus-visible i{opacity:1}
.hs-name-input{font:inherit;font-weight:600;background:var(--ui-bg-tertiary,#1b1b20);color:var(--ui-text-primary);border:1px solid ${SPARK_GREEN};border-radius:5px;padding:1px 6px;width:170px}
.hs-mem-head{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--ui-text-tertiary)}
.hs-mem-head b{font-weight:600;color:var(--ui-text-primary)}
.hs-mem-bar{display:flex;height:8px;margin:4px 0 3px;border-radius:999px;background:var(--ui-stroke-tertiary);overflow:hidden;gap:1px}
.hs-mem-bar>i{display:block;height:100%;background:var(--ui-text-quaternary)}
.hs-mem-bar>i[data-yours=true]{background:${SPARK_GREEN}}
.hs-mem-foot{font-size:10.5px;color:var(--ui-text-quaternary)}
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
    // A heavy, square-cut N drawn as a shape (NVIDIA's own typeface is proprietary), white on green.
    case 'nvidia': return g([
      jsx('rect', { x: 0.5, y: 0.5, width: 15, height: 15, rx: 3, fill: SPARK_GREEN }),
      jsx('polygon', { points: '3.6,12.4 3.6,3.6 6.5,3.6 9.6,8.3 9.6,3.6 12.4,3.6 12.4,12.4 9.5,12.4 6.4,7.7 6.4,12.4', fill: '#fff' })])
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

function dname(n) {
  return (n && (n.title || n.name)) || ''
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
  if (a.kind === 'local') return ['Routed to ', dname((s.nodes || []).find(n => n.id === a.node_id)) || a.node_name, ` · ${a.model || ''}`]
  if (a.kind === 'cloud') return ['Routed to cloud ', `${a.provider}/${a.model}`, a.via === 'failover' ? ' · failover' : '']
  if (a.kind === 'refused') return ['Private inference: no box up · primary held on ', a.node_name || '?', ' · calls fail until a box is back']
  const p = s.primary || {}
  if (s.paused) return ['Paused: you changed the model yourself · Hermes uses ', p.provider || 'its own primary', ' · Auto-pick box resumes']
  return ['Not routed by Local Fleet · Hermes uses ', p.provider || 'its own primary', p.default ? ` · ${p.default}` : '']
}

function chip(s, failed) {
  if (failed) return { tone: 'bad', text: 'fleet · unreachable' }
  if (!s) return { tone: '', text: 'fleet' }
  if (!s.nodes || !s.nodes.length) return { tone: '', text: 'fleet · no boxes' }
  const a = s.applied || {}
  if (s.private_only && ((s.last_decision || {}).target || {}).kind === 'refused') return { tone: 'bad', text: 'fleet · private · no box' }
  if (s.private_only && s.private && !s.private.in_force) return { tone: 'warn', text: 'fleet · private not in force' }
  if (s.down) return { tone: 'bad', text: 'fleet · all down' }
  if (s.paused) return { tone: 'warn', text: 'fleet · paused' }
  if (a.kind === 'local') return { tone: 'spark', text: `fleet · ${dname((s.nodes || []).find(n => n.id === a.node_id)) || a.node_name}${s.private_only ? ' · private' : ''}` }
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
      jsx('span', { children: dname(node) }),
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
const H = 520
const HUB = { x: 150, y: 300 }
// Cloud backup sits straight above the hub, joined by a vertical line.
const CLOUD = { x: 150, y: 74 }

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
  const top = 110
  const span = H - top - 80  // room under the last box for its labels
  const step = rows > 1 ? span / (rows - 1) : 0
  return Array.from({ length: count }, (_, i) => {
    const col = cols === 2 ? i % 2 : 0
    const row = cols === 2 ? Math.floor(i / 2) : i
    return { x: cols === 2 ? 500 + col * 210 : 590, y: rows > 1 ? top + row * step : top + span / 2 }
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
    null
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
    jsx('animateMotion', { dur: '1.8s', begin: `-${delay}s`, repeatCount: 'indefinite', children: jsx('mpath', { href: `#${id}` }) }) }, delay))
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

function boxLine(n, s) {
  const h = n.last_health || {}
  const tier = tierOf(n, s)
  if (n.enabled === false) return 'disabled'
  if (h.status === 'down') return h.detail || 'down'
  if (skipped(n, s)) return `none of ${(s.model_tiers || [s.local_model]).join(', ')}`
  if (tier > 0) return [`fallback · ${s.model_tiers[tier]}`, (n.perf || {}).model === s.model_tiers[tier] ? speed(n) : null].filter(Boolean).join(' · ')
  return [speed(n) || (h.latency_ms != null ? `${h.latency_ms} ms` : null),
    typeof h.load_proxy === 'number' ? (h.load_proxy < 0.05 ? 'idle' : `${Math.round(h.load_proxy * 100)}% busy`) : null,
    n.capacity_gb && h.used_bytes != null ? `${gb(h.used_bytes)}/${n.capacity_gb} GB` : h.free_vram_approx ? `${Math.round(h.free_vram_approx / 1e9)} GB free` : null].filter(Boolean).join(' · ')
}

function residentLine(n) {
  const res = ((n.last_health || {}).resident || []).filter(m => !/embed/i.test(m))
  const r = res.length ? res[0] + (res.length > 1 ? ` +${res.length - 1}` : '') : ''
  return r ? `in memory: ${r.length > 26 ? r.slice(0, 25) + '…' : r}` : ''
}

// Map items: every cluster, plus every box that is not a member of one (members are drawn inside
// their cluster's rack).
function mapItems(nodes) {
  const inCluster = new Set(nodes.flatMap(n => n.members || []))
  return nodes.filter(n => (n.members || []).length || !inCluster.has(n.id))
}

function clusterTotals(c, byId) {
  const ms = (c.members || []).map(id => byId[id]).filter(Boolean)
  const sum = k => ms.reduce((t, m) => t + (m[k] || 0), 0)
  return { members: ms, memory: sum('memory_gb'), forAi: sum('capacity_gb') }
}

function Labels({ x, y, n, s, active, extra }) {
  const marks = marksFor(n)
  const lines = [boxLine(n, s), ...(extra || []), residentLine(n)].filter(Boolean)
  const rs = roles(s, n)
  return jsxs('g', { children: [
    jsx('circle', { cx: x - 8, cy: y - 22, r: 3.5, fill: active ? SPARK_GREEN : TONE_FILL[skipped(n, s) ? 'off' : nodeTone(n)] }),
    ...marks.map(([k, t], j) => jsx(Mark, { kind: k, title: t, x: x + j * 19, y: y - 31, size: 16 }, k)),
    jsx('text', { x: x + 2 + marks.length * 19, y: y - 18, style: { fontWeight: 600 }, children: dname(n) + (active ? '  ← routed' : '') }),
    ...lines.map((t, j) => jsx('text', { className: 't2', x, y: y - 3 + j * 14, children: t }, j)),
    rs.length > 0 && jsx('text', { className: 'hs-roles', x, y: y - 3 + (lines.length + (liveCalls(s, n) > 0 ? 1 : 0)) * 14,
      children: rs.map(([k, label], i) => jsx('tspan', { 'data-k': k, children: (i ? '  ' : '') + label }, k)) }),
    liveCalls(s, n) > 0 && jsx('text', { className: 't2', x, y: y - 3 + lines.length * 14, style: { fill: '#6ee7ff' },
      children: `● live · ${liveCalls(s, n)} call${liveCalls(s, n) === 1 ? '' : 's'}${recentDelegation(s, n) ? ' · subagents' : ''}` })
  ] })
}

// A cluster: its members side by side in a rack, joined by the interconnect. When Hermes is routed
// to it, the link pulses too: one model, split across the boxes.
const CLUSTER_STEP = 150  // spacing of members in a rack; leaves room for the link between them

function ClusterRack({ c, s, x, y, byId, active, live, reduced }) {
  const { members, memory, forAi } = clusterTotals(c, byId)
  const step = CLUSTER_STEP
  const left = x - (step * (members.length - 1)) / 2
  const xs = members.map((_, i) => left + i * step)
  const rack = { x: xs[0] - 66, y: y - 62, w: xs[xs.length - 1] - xs[0] + 132, h: 112 }
  const linkY = y + 6
  const linkD = xs.length > 1 ? `M${xs[0] + 48} ${linkY} L${xs[xs.length - 1] - 48} ${linkY}` : ''
  const linkId = `hs-link-${c.id}`
  const busy = active || live
  const extra = [`${members.length} boxes${c.link ? ` · ${c.link}` : ''}${memory ? ` · ${memory} GB` : ''}${forAi ? ` (${forAi} for AI)` : ''}`]
  return jsxs('g', { children: [
    jsx('rect', { x: rack.x, y: rack.y, width: rack.w, height: rack.h, rx: 12, fill: 'none',
      stroke: active ? SPARK_GREEN : 'var(--ui-stroke-secondary)', strokeDasharray: active ? undefined : '4 4', strokeWidth: active ? 1.5 : 1 }),
    jsx('text', { className: 't3', x: rack.x + 10, y: rack.y + 14, children: (c.title || c.name).toUpperCase() }),
    ...members.map((m, i) => jsx(IsoServer, { x: xs[i], y, tone: nodeTone(m) === 'off' ? 'off' : nodeTone(c), active: active, load: (c.last_health || {}).load_proxy }, m.id)),
    linkD && jsx('path', { id: linkId, d: linkD, fill: 'none', stroke: busy ? SPARK_GREEN : 'var(--ui-stroke-secondary)', strokeWidth: 4, strokeLinecap: 'round',
      strokeDasharray: busy ? '2 7' : undefined, className: busy && !reduced ? 'hs-link-live' : undefined }),
    linkD && c.link && jsx('text', { className: 't2', x: (xs[0] + xs[xs.length - 1]) / 2, y: rack.y + rack.h - 9, textAnchor: 'middle', children: c.link }),
    ...members.map((m, i) => jsx('text', { className: 't2', x: xs[i], y: y + 62, textAnchor: 'middle', children: dname(m) }, `n-${m.id}`)),
    jsx(Labels, { x: rack.x + rack.w + 18, y: y - 8, n: c, s, active, extra })
  ] })
}

function FleetMap({ s, onSelect }) {
  const nodes = s.nodes || []
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
  const items = mapItems(nodes)
  const pos = nodePositions(items.length)
  const a = s.applied || {}
  const cloudLive = a.kind === 'cloud'
  const reduced = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const hubEdge = { x: HUB.x + 46, y: HUB.y }
  const cloudPath = `M${HUB.x} ${HUB.y - 46} L${CLOUD.x} ${CLOUD.y + 16}`
  // An item is active when Hermes is routed to it, or (for a cluster) to one of its members.
  const activeOf = n => a.kind === 'local' && (a.node_id === n.id || (n.members || []).includes(a.node_id))
  const isCluster = n => (n.members || []).length > 0
  const wireEnd = (n, p) => isCluster(n)
    ? { x: p.x - (CLUSTER_STEP * (n.members.length - 1)) / 2 - 70, y: p.y + 4 }
    : { x: p.x - 50, y: p.y + 4 }
  return jsx('div', { className: 'hs-map', children: jsxs('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Local Fleet map', children: [
    jsx('path', { id: 'hs-wire-cloud', className: 'hs-wire', 'data-cloud': true, 'data-live': cloudLive, d: cloudPath }),
    cloudLive && !reduced && Packets({ id: 'hs-wire-cloud', color: 'var(--ui-orange,#df6500)' }),
    ...items.map((n, i) => {
      const active = activeOf(n)
      const tone = skipped(n, s) ? 'off' : nodeTone(n)
      const id = `hs-wire-${n.id}`
      const busy = !active && liveCalls(s, n) > 0
      return jsxs('g', { children: [
        jsx('path', { id, className: 'hs-wire', 'data-live': active, 'data-traffic': busy, 'data-off': !busy && (tone === 'off' || tone === 'bad'), d: wirePath(hubEdge, wireEnd(n, pos[i])) }),
        (active || busy) && !reduced && Packets({ id, color: active ? SPARK_GREEN : '#6ee7ff' })
      ] }, `w-${n.id}`)
    }),
    jsx(Hub, { s }),
    jsx(Cloud, { s, live: cloudLive }),
    ...items.map((n, i) => {
      const { x, y } = pos[i]
      const active = activeOf(n)
      if (isCluster(n)) {
        return jsx('g', { className: 'hs-pick', onClick: () => onSelect && onSelect(n.id), children: jsx(ClusterRack, { c: n, s, x, y, byId, active, live: liveCalls(s, n) > 0, reduced }) }, n.id)
      }
      const tone = skipped(n, s) || (s.exclusions || {})[n.id] ? 'off' : nodeTone(n)
      return jsxs('g', { className: 'hs-pick', onClick: () => onSelect && onSelect(n.id), children: [
        jsx(IsoServer, { x, y, tone, active, load: (n.last_health || {}).load_proxy }),
        jsx(Labels, { x: x + 70, y, n, s, active })
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

function gb(bytes) {
  const v = bytes / 1e9
  return v >= 10 ? Math.round(v) : Math.round(v * 10) / 10
}

// Apple silicon, GB10 (DGX Spark / GX10) and Strix Halo share one pool between CPU and GPU.
function memoryWord(n) {
  const vendor = ((n.platform || {}).vendor) || ''
  const hint = `${n.name} ${(n.labels || []).join(' ')}`.toLowerCase()
  const unified = vendor === 'apple' || /gb10|spark|gx10|dgx|strix|halo/.test(hint)
  return unified ? 'unified memory' : 'memory'
}

// Box memory: total (memory_gb), what models may use (capacity_gb), and one bar segment per loaded
// model, yours in green.
function MemoryPanel({ n, s }) {
  const h = n.last_health || {}
  const sizes = h.sizes || {}
  const used = h.used_bytes != null ? h.used_bytes : Object.values(sizes).reduce((a, b) => a + b, 0)
  const cap = n.capacity_gb ? n.capacity_gb * 1e9 : 0
  const tiers = s.model_tiers || []
  const total = n.memory_gb ? `${n.memory_gb} GB ${memoryWord(n)}` : null
  const head = [total, n.capacity_gb ? `${n.capacity_gb} GB for AI` : null].filter(Boolean).join(' · ') || 'memory'
  const models = (h.models || n.models || []).filter(m => !/embed/i.test(m))
  return jsxs('div', { className: 'hs-mem', children: [
    jsxs('div', { className: 'hs-mem-head', children: [
      jsx('b', { children: head }),
      jsx('span', { children: cap ? `${gb(used)} / ${n.capacity_gb} GB used · ${gb(Math.max(0, cap - used))} GB free` : used ? `${gb(used)} GB loaded` : 'nothing loaded' })
    ] }),
    cap ? jsx('div', { className: 'hs-mem-bar', children: Object.entries(sizes).map(([m, b]) =>
      jsx('i', { 'data-yours': tiers.includes(m), title: `${m} · ${gb(b)} GB`, style: { width: `${Math.max(1, (b / cap) * 100)}%` } }, m)) }) : null,
    jsx('div', { className: 'hs-mem-foot', children: [h.version ? `${n.kind === 'ollama' ? 'Ollama' : n.kind} ${h.version}` : n.kind,
      `${models.length} model${models.length === 1 ? '' : 's'} installed`].join(' · ') })
  ] })
}

// Click the name to rename the box; Enter saves, Escape cancels, an empty name goes back to the handle.
function EditableName({ ctx, n }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const save = async () => {
    setEditing(false)
    if ((value.trim() || null) === (n.title || null)) return
    try {
      qc.setQueryData(KEY, await ctx.rest('/rename', { method: 'POST', body: { node: n.id, title: value.trim() } }))
    } catch (err) {
      host.notifyError(err, 'Rename failed')
    }
  }
  if (editing) {
    return jsx('input', { className: 'hs-name-input', autoFocus: true, value, maxLength: 40, placeholder: n.name,
      'aria-label': `Display name for ${n.name}`, onChange: e => setValue(e.target.value), onBlur: save,
      onKeyDown: e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) } })
  }
  return jsxs('button', { type: 'button', className: 'hs-name-btn', title: 'Rename', onClick: () => { setValue(n.title || ''); setEditing(true) }, children: [
    jsx('span', { children: dname(n) }),
    n.title && jsx('small', { children: n.name }),
    jsx('i', { 'aria-hidden': true, children: '✎' })
  ] })
}

function CardActions({ n, s, run, busy, onWhy }) {
  const ex = (s.exclusions || {})[n.id]
  return jsxs('div', { className: 'hs-card-actions', children: [
    jsx('button', { type: 'button', className: 'hs-link', onClick: onWhy, children: 'Why?' }),
    ex ? jsx('button', { type: 'button', className: 'hs-link', disabled: busy, onClick: () => run('include', '/include', { node: n.id }),
      children: ex.kind === 'maintenance' ? 'End maintenance' : 'End rehearsal' })
      : [jsx('button', { type: 'button', className: 'hs-link', disabled: busy, title: 'Pretend this box is down for 10 minutes, inside Local Fleet only: nothing is stopped on the box',
          onClick: () => run('rehearse', '/exclude', { node: n.id, kind: 'rehearsal', minutes: 10 }), children: 'Rehearse outage' }, 'r'),
        jsx('button', { type: 'button', className: 'hs-link', disabled: busy, title: 'Leave this box out of new selections; requests already running there finish',
          onClick: () => run('maintenance', '/exclude', { node: n.id, kind: 'maintenance' }), children: 'Maintenance' }, 'm')]
  ] })
}

function NodeCard({ n, s, ctx, run, busy, onWhy }) {
  const h = n.last_health || {}
  const cluster = (n.members || []).length > 0
  const byId = Object.fromEntries((s.nodes || []).map(x => [x.id, x]))
  const parents = (s.nodes || []).filter(c => (c.members || []).includes(n.id))
  const active = (s.applied || {}).kind === 'local' && (s.applied || {}).node_id === n.id
  const want = s.local_model
  const models = (h.models || n.models || []).filter(m => !/embed/i.test(m))
  return jsxs('div', { className: 'hs-card', 'data-active': active, 'data-cluster': cluster, children: [
    jsxs('div', { className: 'hs-card-head', children: [
      jsx('span', { className: 'hs-dot', 'data-tone': active ? 'spark' : { ok: 'ok', warn: 'warn', bad: 'bad' }[nodeTone(n)] || '' }),
      jsx(Marks, { n, size: 15 }),
      ctx ? jsx(EditableName, { ctx, n }) : jsx('span', { children: dname(n) }),
      cluster && jsx('em', { className: 'hs-badge', style: { fontStyle: 'normal' }, children: `cluster · ${n.members.length} boxes${n.link ? ' · ' + n.link : ''}` }),
      ...parents.map(c => jsx('em', { className: 'hs-badge', style: { fontStyle: 'normal' }, title: 'Shares its memory with this cluster', children: `in ${dname(c)}` }, c.id)),
      (s.exclusions || {})[n.id] && jsx('em', { className: 'hs-badge', 'data-kind': 'ex', style: { fontStyle: 'normal' },
        children: (s.exclusions[n.id].kind === 'maintenance' ? 'maintenance' : 'rehearsal') }),
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
    jsx('div', { className: 'hs-card-sub', title: s.hide_addresses ? undefined : n.base_url,
      children: `${n.kind} · ${(n.labels || []).join(', ') || 'no labels'}${s.hide_addresses ? '' : ' · ' + n.base_url}` }),
    cluster
      ? jsx('div', { className: 'hs-cluster-members', children: n.members.map(id => byId[id]).filter(Boolean).map(m =>
          jsxs('div', { children: [jsx('div', { className: 'hs-mem-who', children: dname(m) }), jsx(MemoryPanel, { n: m, s })] }, m.id)) })
      : jsx(MemoryPanel, { n, s }),
    jsx(Sparkline, { points: (s.series || {})[n.id] }),
    run && jsx(CardActions, { n, s, run, busy, onWhy }),
    jsx('div', { className: 'hs-models', children: models.slice(0, 8).map(m => jsx('span', {
      'data-want': m === want, 'data-fallback': (s.model_tiers || []).slice(1).includes(m),
      title: m === want ? `${m} (your main model)` : (s.model_tiers || []).includes(m) ? `${m} (fallback model)` : m, children: m }, m)) })
  ] })
}

// ---------------------------------------------------------------------------
// Operations: decision inspector, flight recorder, rehearsal / maintenance, drift, readiness,
// savings audit and the doctor drawer. All read the same /status snapshot; actions call the
// plugin's own routes and never touch anything outside Hermes's config and Local Fleet's files.

function Drawer({ title, onClose, children }) {
  return jsxs('div', { className: 'hs-drawer-wrap', onClick: e => { if (e.target === e.currentTarget) onClose() }, children: [
    jsxs('aside', { className: 'hs-drawer', role: 'dialog', 'aria-label': title, children: [
      jsxs('div', { className: 'hs-drawer-head', children: [jsx('b', { children: title }),
        jsx('button', { type: 'button', className: 'hs-link', onClick: onClose, 'aria-label': 'Close', children: 'Close' })] }),
      jsx('div', { className: 'hs-drawer-body', children })
    ] })
  ] })
}

// How old a box's probe is, against the probe interval: fresh, stale (older than three intervals) or never.
function fresh(s, iso) {
  if (!iso) return 'never'
  const age = (Date.now() - Date.parse(iso)) / 1000
  return age > 3 * (s.probe_interval_s || 30) ? 'stale' : 'fresh'
}

function WhyPanel({ s, focus, onRecheck, busy }) {
  const d = s.decision || s.last_decision || {}
  const cands = d.candidates || []
  if (!cands.length) {
    return jsxs('div', { children: [jsx('p', { className: 'hs-page-hint', children: 'No decision recorded yet.' }),
      jsx(Button, { size: 'sm', onClick: onRecheck, disabled: busy, children: busy ? 'Checking…' : 'Check now' })] })
  }
  const t = d.target || {}
  return jsxs('div', { className: 'hs-why', children: [
    jsxs('div', { className: 'hs-why-head', children: [
      jsx('div', { className: 'hs-why-route', children: t.kind === 'cloud' ? `Cloud · ${t.provider}/${t.model}` : t.kind === 'refused' ? `Refused (private inference)${t.node_name ? ` · held on ${t.node_name}` : ''}` : `${t.node_name || '—'} · ${t.model || ''}` }),
      jsx('div', { children: d.reason }),
      jsx('small', { children: `mode ${d.mode}${d.pinned ? ' · pinned' : ''} · model ${d.tier_model || '(each box its own)'}${d.tier ? ` · fallback tier ${d.tier}` : ''} · decided ${ago(d.at)}` })
    ] }),
    jsx('table', { className: 'hs-why-table', children: jsxs('tbody', { children: [
      jsxs('tr', { children: ['', 'Box', 'Load', 'Latency', 'tok/s', 'Free', 'Probed', 'Verdict'].map(h => jsx('th', { children: h }, h)) }),
      ...cands.map(c => jsxs('tr', { 'data-chosen': c.chosen, 'data-out': !c.eligible, 'data-focus': focus === c.id, children: [
        jsx('td', { children: c.chosen ? '→' : '' }),
        jsx('td', { children: c.title || c.name }),
        jsx('td', { children: c.load == null ? '—' : jsx('span', { className: 'hs-meter', 'data-busy': c.load > 0.75, children: jsx('i', { style: { width: `${Math.max(3, c.load * 100)}%` } }) }) }),
        jsx('td', { children: c.latency_ms == null ? '—' : `${c.latency_ms} ms` }),
        jsx('td', { children: c.tps || '—' }),
        jsx('td', { children: c.free_bytes ? `${Math.round(c.free_bytes / 1e9)} GB` : '—' }),
        jsx('td', { title: c.checked_at || 'never probed', 'data-stale': fresh(s, c.checked_at) !== 'fresh', children: fresh(s, c.checked_at) === 'never' ? 'never' : `${ago(c.checked_at)}${fresh(s, c.checked_at) === 'stale' ? ' · stale' : ''}` }),
        jsx('td', { children: `${c.eligible ? 'eligible' : 'out'} · ${c.reason}${c.least_busy ? ' · least busy' : ''}` })
      ] }, c.id))
    ] }) }),
    jsx('p', { className: 'hs-page-hint', children: 'Eligible boxes are ranked by load, then your preferred labels, then speed on this model, then free memory, then latency. A healthy box Hermes is already on is kept unless another is clearly less busy.' }),
    jsx(Button, { size: 'sm', variant: 'outline', onClick: onRecheck, disabled: busy, children: busy ? 'Checking…' : 'Check again (probes, changes nothing)' })
  ] })
}

const EVENT_LABEL = { route: 'configured', served: 'served', health: 'health', rehearsal: 'rehearsal', maintenance: 'maintenance', drift: 'drift', aux: 'side tasks', refused: 'refused', private: 'private' }

function Recorder({ events }) {
  const items = (events || []).slice().reverse().slice(0, 14)
  if (!items.length) return jsx('div', { className: 'hs-page-hint', children: 'Nothing recorded yet. Routing changes, health changes, rehearsals and what Hermes actually served will appear here.' })
  return jsxs('div', { children: [
    jsxs('div', { className: 'hs-rec-legend', children: [
      jsx('span', { 'data-k': 'route', children: 'configured: what Local Fleet set' }),
      jsx('span', { 'data-k': 'served', children: 'served: what actually answered' }),
      jsx('span', { 'data-k': 'health', children: 'health' }), jsx('span', { 'data-k': 'rehearsal', children: 'rehearsal / maintenance' })] }),
    jsx('div', { className: 'hs-timeline', children: items.map((e, i) => jsxs('div', { className: 'hs-ev', 'data-k': e.kind, children: [
      jsx('em', { children: EVENT_LABEL[e.kind] || e.kind }), ' ', e.text,
      jsx('small', { children: `${ago(new Date((e.t || 0) * 1000).toISOString())}${e.reason ? ` · ${e.reason}` : ''}` })
    ] }, `${e.t}-${i}`)) })
  ] })
}

function PrivateBanner({ s, run, busy }) {
  const p = s.private || {}
  if (!s.private_only || p.in_force) return null
  return jsxs('div', { className: 'hs-drift', role: 'status', children: [
    jsxs('div', { children: [jsx('b', { children: 'Private inference is not fully in force. ' }),
      (p.problems || []).map(x => `${x.what}: ${x.detail}`).join(' · '), '. Local Fleet re-applies what it owns; the rest needs a change in config.yaml.'] }),
    jsx(Button, { size: 'sm', disabled: busy, onClick: () => run('private', '/private', { on: true }), children: 'Apply again' })
  ] })
}

function DriftBanner({ s, run, busy }) {
  const items = s.drift || []
  if (!items.length) return null
  return jsxs('div', { className: 'hs-drift', role: 'status', children: [
    jsxs('div', { children: [jsx('b', { children: 'Changed outside Local Fleet. ' }),
      items.map(d => d.detail).join(' · '), '. Local Fleet will not overwrite it on its own.'] }),
    jsx(Button, { size: 'sm', disabled: busy, onClick: () => run('reapply', '/reapply'), children: 'Reapply' }),
    jsx(Button, { size: 'sm', variant: 'outline', disabled: busy, onClick: () => run('relinquish', '/relinquish'), children: 'Stop managing' })
  ] })
}

function ReadinessMatrix({ s }) {
  const tiers = s.model_tiers || []
  const rows = (s.nodes || []).filter(n => !(n.members || []).length)
  if (!tiers.length) return jsx('div', { className: 'hs-page-hint', children: 'Set a local model (hermes fleet model) to check which boxes can run Hermes on it.' })
  const cell = v => (v === true ? '✓' : v === false ? '✗' : '?')
  return jsx('table', { className: 'hs-why-table hs-ready', children: jsxs('tbody', { children: [
    jsxs('tr', { children: ['Box', 'Model', 'Tools', 'Vision', 'Context', 'Verdict'].map(h => jsx('th', { children: h }, h)) }),
    ...rows.flatMap(n => {
      const installed = tiers.filter(m => ((n.last_health || {}).models || []).includes(m))
      if (!installed.length) {
        return [jsxs('tr', { 'data-out': true, children: [jsx('td', { children: dname(n) }), jsx('td', { colSpan: 4, children: 'none of your models installed' }), jsx('td', { children: 'not a candidate' })] }, `${n.id}-none`)]
      }
      return installed.map((m, j) => {
      const i = tiers.indexOf(m)
      const has = true
      const c = (n.caps || {})[m] || {}
      const ctx = c.context ? `${Math.round(c.context / 1024)}k` : '?'
      const rejected = has && (c.tools === false || (c.context && s.min_context && c.context < s.min_context))
      const warn = has && !rejected && !c.context && (c.source || '').startsWith('verified')
      return jsxs('tr', { 'data-out': !has || rejected, title: c.source ? `${c.source}${c.context_source ? ' · context: ' + c.context_source : ''}` : 'not checked yet', children: [
        jsx('td', { children: j === 0 ? dname(n) : '' }),
        jsx('td', { children: `${m}${i ? ' (fallback)' : ''}` }),
        jsx('td', { children: has ? cell(c.tools) : '' }),
        jsx('td', { children: has ? cell(c.vision) : '' }),
        jsx('td', { children: has ? `${ctx}${c.context_source ? ` · ${c.context_source.split(' (')[0]}` : ''}` : '' }),
        jsx('td', { children: !has ? 'not installed' : rejected ? 'rejected' : warn ? 'context not set: may truncate Hermes' : c.source ? 'ok' : 'not checked' })
      ] }, `${n.id}-${m}`)
      })
    })
  ] }) })
}

function SavingsPanel({ s }) {
  const t = s.traffic || {}
  const b = t.breakdown || {}
  if (t.saved == null) return jsx('p', { className: 'hs-page-hint', children: 'Set your cloud model\'s price first: hermes fleet price <input> <output> --currency GBP' })
  const n = v => (v || 0).toLocaleString()
  return jsxs('div', { className: 'hs-savings', children: [
    jsxs('div', { className: 'hs-why-route', children: [money(s, t.saved), ' avoided this week'] }),
    jsx('table', { className: 'hs-why-table', children: jsxs('tbody', { children: [
      jsxs('tr', { children: [jsx('th', { children: '' }), jsx('th', { children: 'Tokens run locally' }), jsx('th', { children: 'Rate per million' }), jsx('th', { children: 'Value' })] }),
      jsxs('tr', { children: [jsx('td', { children: 'Input' }), jsx('td', { children: n(b.local_in) }), jsx('td', { children: money(s, b.price_in_per_m || 0) }), jsx('td', { children: money(s, b.saved_in || 0) })] }),
      jsxs('tr', { children: [jsx('td', { children: 'Output' }), jsx('td', { children: n(b.local_out) }), jsx('td', { children: money(s, b.price_out_per_m || 0) }), jsx('td', { children: money(s, b.saved_out || 0) })] }),
      jsxs('tr', { children: [jsx('td', { children: 'of which side tasks' }), jsx('td', { children: n((b.aux_in || 0) + (b.aux_out || 0)) }), jsx('td', { children: '' }), jsx('td', { children: '' })] })
    ] }) }),
    jsx('p', { children: `Baseline: ${(b.baseline || {}).model || 'not recorded'} at the rates you entered (${(b.baseline || {}).source || 'hermes fleet price'}). Tokens are what Hermes's own per-call usage reported.` }),
    jsx('p', { children: `Coverage: ${b.calls_local_counted || 0} of ${b.calls_local || 0} local calls reported token counts${b.coverage != null ? ` (${Math.round(b.coverage * 100)}%)` : ''}. Not counted: ${b.excluded || ''}.` }),
    jsx('p', { className: 'hs-caveat', children: b.caveat })
  ] })
}

const LEVEL_ICON = { ok: '✓', info: '·', warn: '!', error: '✗' }

function DoctorPanel({ ctx, run, busy }) {
  const dq = useQuery({ queryKey: [ID, 'doctor'], queryFn: () => ctx.rest('/doctor', { timeoutMs: 60000 }), staleTime: 0 })
  const act = async (action) => {
    if (action === 'probe') await run('probe', '/probe')
    else if (action === 'use') await run('use', '/use', { node: 'best' })
    else if (action === 'reapply') await run('reapply', '/reapply')
    else if (action === 'relinquish') await run('relinquish', '/relinquish')
    else if (action.startsWith('include:')) await run('include', '/include', { node: action.slice(8) })
    dq.refetch()
  }
  const checks = (dq.data || {}).checks || []
  if (dq.isLoading) return jsx('p', { className: 'hs-page-hint', children: 'Checking every box…' })
  return jsxs('div', { className: 'hs-doctor', children: [
    ...checks.map(c => jsxs('div', { className: 'hs-check', 'data-level': c.level, children: [
      jsx('span', { className: 'hs-check-icon', children: LEVEL_ICON[c.level] }),
      jsxs('div', { className: 'hs-check-body', children: [jsx('b', { children: c.title }), c.detail && jsx('div', { children: c.detail }),
        c.fix && c.fix.command && jsx('code', { children: c.fix.command }),
        c.fix && c.fix.action && jsxs('div', { className: 'hs-check-actions', children: [
          jsx(Button, { size: 'sm', disabled: busy, onClick: () => act(c.fix.action), children: c.fix.label }),
          c.fix.alt && jsx(Button, { size: 'sm', variant: 'outline', disabled: busy, onClick: () => act(c.fix.alt.action), children: c.fix.alt.label })] })] })
    ] }, c.id)),
    jsx('p', { className: 'hs-page-hint', children: 'Complements hermes doctor (Hermes itself) and hermes plugins doctor (packaging).' }),
    jsx(Button, { size: 'sm', variant: 'outline', onClick: () => dq.refetch(), children: 'Run again' })
  ] })
}

function roles(s, n) {
  const a = s.applied || {}
  const out = []
  if (a.kind === 'local' && (a.node_id === n.id || (n.members || []).includes(a.node_id))) out.push(['chat', 'chat'])
  if (s.aux && s.aux.node_id === n.id) out.push(['aux', s.aux.tasks.map(t => t === 'title_generation' ? 'titles' : t).join(' · ')])
  if (recentDelegation(s, n)) out.push(['sub', 'subagents'])
  const ex = (s.exclusions || {})[n.id]
  if (ex) out.push(['ex', ex.kind === 'maintenance' ? 'maintenance' : 'rehearsal'])
  return out
}

function FleetPage({ ctx }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')
  // {kind: 'why' | 'doctor' | 'savings', node?}; ?drawer=why|doctor|savings opens one, for previews
  const [drawer, setDrawer] = useState(() => {
    const k = new URLSearchParams(window.location.search).get('drawer')
    return k ? { kind: k } : null
  })
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
      jsxs('button', { type: 'button', className: 'hs-stat hs-stat-btn', onClick: () => setDrawer({ kind: 'savings' }),
        title: (s.traffic || {}).saved == null ? 'Set a cloud price: hermes fleet price <in> <out> --currency GBP' : 'How this is worked out', children: [
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
      jsxs('button', { type: 'button', className: 'hs-toggle', role: 'switch', 'aria-checked': Boolean(s.keep_loaded), disabled: Boolean(busy),
        title: 'While Hermes is routed to a box, keep its model in memory so the first message after a quiet spell does not wait for a load',
        onClick: () => run('keep', '/keep', { on: !s.keep_loaded }), children: [jsx('i', {}), 'Keep model loaded'] }),
      jsxs('button', { type: 'button', className: 'hs-toggle', role: 'switch', 'aria-checked': Boolean(s.aux), disabled: Boolean(busy),
        title: s.aux ? `${s.aux.tasks.join(', ')} → ${s.aux.node_name}` : 'Session titles and compression run on the least busy box, with cloud as backup',
        onClick: () => run('aux', '/aux', { on: !s.aux }), children: [jsx('i', {}), 'Side tasks on fleet'] }),
      jsxs('button', { type: 'button', className: 'hs-toggle', role: 'switch', 'aria-checked': Boolean(s.private_only), disabled: Boolean(busy),
        title: s.private_only ? ((s.private || {}).in_force ? 'In force: primary, fallback_providers, side tasks and subagents are on your boxes. Tools such as web search still use the internet.' : 'On, but not fully in force: see the banner') : 'Keep Hermes\'s model calls on your boxes: cloud fallback comes off, subagents use the fleet, and with no box up calls fail rather than reach cloud. Tools such as web search still use the internet.',
        onClick: () => run('private', '/private', { on: !s.private_only }), children: [jsx('i', {}), 'Private inference'] }),
      jsx(Button, { size: 'sm', variant: 'outline', onClick: () => setDrawer({ kind: 'doctor' }), children: 'Doctor' }),
      jsx('span', { className: 'hs-page-hint', style: { marginLeft: 'auto' }, children: s.last_probe_at ? `probed ${ago(s.last_probe_at)} · refreshes every 10 s` : '' })
    ] }),
    jsx(PrivateBanner, { s, run, busy: Boolean(busy) }),
    jsx(DriftBanner, { s, run, busy: Boolean(busy) }),
    jsx(FleetMap, { s, onSelect: id => setDrawer({ kind: 'why', node: id }) }),
    jsx('div', { className: 'hs-cards', children: nodes.slice().sort((x, y) => ((y.members || []).length > 0) - ((x.members || []).length > 0)).map(n =>
      jsx(NodeCard, { n, s, ctx, run, busy: Boolean(busy), onWhy: () => setDrawer({ kind: 'why', node: n.id }) }, n.id)) }),
    jsx('div', { className: 'hs-section', children: 'Readiness: can each box run Hermes on your models?' }),
    jsx(ReadinessMatrix, { s }),
    jsx('div', { className: 'hs-section', children: 'Flight recorder' }),
    jsx(Recorder, { events: s.events }),
    drawer && drawer.kind === 'why' && jsx(Drawer, { title: 'Why this box?', onClose: () => setDrawer(null),
      children: jsx(WhyPanel, { s, focus: drawer.node, busy: busy === 'why', onRecheck: () => run('why', '/why') }) }),
    drawer && drawer.kind === 'doctor' && jsx(Drawer, { title: 'Fleet doctor', onClose: () => setDrawer(null),
      children: jsx(DoctorPanel, { ctx, run, busy: Boolean(busy) }) }),
    drawer && drawer.kind === 'savings' && jsx(Drawer, { title: 'Cloud spend avoided: the working', onClose: () => setDrawer(null),
      children: jsx(SavingsPanel, { s }) })
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
