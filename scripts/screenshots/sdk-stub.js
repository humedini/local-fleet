// Minimal stand-in for @hermes/plugin-sdk, enough to render desktop/plugin.js outside the app
// for screenshots. Not used by the plugin itself.
import { useEffect, useState, createElement as h } from 'react'
export const ROUTES_AREA = 'routes', SIDEBAR_NAV_AREA = 'nav', PALETTE_AREA = 'palette', THEMES_AREA = 'themes'
export const MODEL_MENU_ROW_AREA = 'modelMenu', COMPOSER_AREAS = { modelPill: 'composer.modelPill' }
export const STATUSBAR_AREAS = { right: 'statusBar.right' }
export const host = { notify() {}, notifyError() {}, navigate() {} }
export const haptic = () => {}, requestTheme = () => {}
export const useTheme = () => ({ themeName: 'nous', setTheme() {} })
export function Button({ size, variant, children, ...p }) {
  return h('button', { ...p, className: `btn ${variant || 'default'} ${size || ''}` }, children)
}
export const Popover = ({ children }) => h('div', { className: 'pop-wrap' }, children)
export const PopoverTrigger = ({ children }) => children
export const PopoverContent = ({ children, className }) => h('div', { className: `pop ${className || ''}` }, children)
export function useQuery({ queryFn }) {
  const [d, setD] = useState(null)
  useEffect(() => { queryFn().then(setD) }, [])
  return { data: d, isError: false, refetch() {} }
}
export const useQueryClient = () => ({ setQueryData() {} })
