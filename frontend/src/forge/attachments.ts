import { useEffect, useState } from 'react'
import { api } from '../api'

/** Display helpers for the forgeAttachment block. Mirrors the backend's
 * blocks.ext_label / blocks.format_bytes so the editor and the published
 * page label a file identically. */

/** 'annex-c.pdf' → 'PDF'. Falls back to the MIME subtype, then 'FILE'. */
export function extLabel(filename: string, mime: string): string {
  if (filename.includes('.')) {
    const ext = filename.split('.').pop()?.trim().toUpperCase()
    if (ext) return ext.slice(0, 5)
  }
  if (mime.includes('/')) return (mime.split('/').pop() || 'file').toUpperCase().slice(0, 5)
  return 'FILE'
}

/** 2517621 → '2.4 MB'. Powers of 1024, one decimal below 10 units. */
export function formatBytes(size: number): string {
  if (!size || size <= 0) return ''
  const units = ['bytes', 'KB', 'MB', 'GB']
  let value = size
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  if (idx === 0) return `${Math.round(value)} bytes`
  return `${value < 10 ? value.toFixed(1) : value.toFixed(0)} ${units[idx]}`
}

/** URL-safe slug. Mirrors python-slugify closely enough for the editor's live
 * URL preview; the backend's value is authoritative at publish time. */
function slug(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

const SLUG_MAX = 60

/** Where an attachment publishes to, relative to the SITE root. Mirrors
 * blocks.attachment_published_path — see that docstring for the rules. */
export function publishedPath(name: string, filename: string, path = ''): string {
  const ext = filename.includes('.') ? `.${filename.split('.').pop()!.toLowerCase()}` : ''
  const segments = path
    .split(/[\\/]+/)
    .map((s) => s.trim())
    .filter((s) => s && s !== '.' && s !== '..')

  let stemSource = ''
  if (segments.length && segments[segments.length - 1].includes('.')) {
    stemSource = segments.pop()!.replace(/\.[^.]*$/, '')
  }
  if (!stemSource) stemSource = name.trim() || filename.replace(/\.[^.]*$/, '')

  const folders = segments.map(slug).filter(Boolean)
  const stem = slug(stemSource).slice(0, SLUG_MAX).replace(/^-+|-+$/g, '') || 'attachment'
  return [...folders, `${stem}${ext}`].join('/')
}

/** The published site's base URL, fetched once per session for the URL
 * preview. Failures are silent — the preview just falls back to the path. */
let baseUrlPromise: Promise<string> | null = null

export function siteBaseUrl(): Promise<string> {
  baseUrlPromise ??= api
    .settings()
    .then((s) => (s.publishing?.base_url || '').replace(/\/+$/, ''))
    .catch(() => '')
  return baseUrlPromise
}

export function useSiteBaseUrl(): string {
  const [base, setBase] = useState('')
  useEffect(() => {
    let live = true
    void siteBaseUrl().then((b) => {
      if (live) setBase(b)
    })
    return () => {
      live = false
    }
  }, [])
  return base
}
