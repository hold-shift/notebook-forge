/** Presentational editor card for forgeDocGroup blocks.
 * Shows a group chooser + config controls + a live member preview. */

import { useEffect, useState } from 'react'
import type { GroupInfo, GroupMember } from '../api'
import { api } from '../api'
import { startYear } from '../lib/librarySort'

export type SortOption = 'manual' | 'date_range' | 'title_az' | 'last_updated'
export type LayoutOption = 'list' | 'compact_grid'

export interface ForgeDocGroupProps {
  groupId: string
  sort: SortOption
  showBlurbs: boolean
  showWordCounts: boolean
  layout: LayoutOption
}

export interface ForgeDocGroupViewProps {
  props: ForgeDocGroupProps
  onChange?: (patch: Partial<ForgeDocGroupProps>) => void
}

function sortMembers(members: GroupMember[], sort: SortOption): GroupMember[] {
  const copy = [...members]
  if (sort === 'manual') return copy.sort((a, b) => a.group_position - b.group_position)
  if (sort === 'date_range') return copy.sort((a, b) => startYear(a.slug) - startYear(b.slug))
  if (sort === 'title_az') return copy.sort((a, b) => a.title.localeCompare(b.title))
  if (sort === 'last_updated') return copy // delivered in last_updated order from API
  return copy
}

const SORT_LABELS: Record<SortOption, string> = {
  manual: 'Manual order',
  date_range: 'Date range',
  title_az: 'Title A–Z',
  last_updated: 'Last updated',
}

export function ForgeDocGroupView({ props, onChange }: ForgeDocGroupViewProps) {
  const [groups, setGroups] = useState<GroupInfo[]>([])

  const load = () => api.groups().then(setGroups, () => {})

  useEffect(() => {
    load()
    window.addEventListener('focus', load)
    return () => window.removeEventListener('focus', load)
  }, [])

  const selectedGroup = groups.find((g) => String(g.id) === props.groupId)
  const sorted = selectedGroup ? sortMembers(selectedGroup.members, props.sort) : []
  const preview = sorted.slice(0, 5)
  const overflow = sorted.length - 5

  const color = selectedGroup?.color ?? '#9c5a3c'

  return (
    <div
      className={`forge-docgroup${!selectedGroup && props.groupId ? ' warn' : ''}`}
      data-testid="forge-docgroup"
      contentEditable={false}
    >
      <div className="forge-docgroup-header">
        <i className="ti ti-folders" aria-hidden />
        <select
          value={props.groupId}
          aria-label="Choose group"
          onChange={(e) => onChange?.({ groupId: e.target.value })}
        >
          <option value="">Choose a group…</option>
          {groups.map((g) => (
            <option key={g.id} value={String(g.id)}>
              {g.name}
            </option>
          ))}
        </select>
        {selectedGroup && (
          <span className="group-dot" style={{ background: color }} aria-hidden />
        )}
      </div>

      <div className="forge-docgroup-config">
        <select
          value={props.sort}
          aria-label="Sort order"
          onChange={(e) => onChange?.({ sort: e.target.value as SortOption })}
        >
          {(Object.keys(SORT_LABELS) as SortOption[]).map((k) => (
            <option key={k} value={k}>
              {SORT_LABELS[k]}
            </option>
          ))}
        </select>
        <label className="forge-docgroup-check">
          <input
            type="checkbox"
            checked={props.showBlurbs}
            onChange={(e) => onChange?.({ showBlurbs: e.target.checked })}
          />
          Blurbs
        </label>
        <label className="forge-docgroup-check">
          <input
            type="checkbox"
            checked={props.showWordCounts}
            onChange={(e) => onChange?.({ showWordCounts: e.target.checked })}
          />
          Word counts
        </label>
        <select
          value={props.layout}
          aria-label="Layout"
          onChange={(e) => onChange?.({ layout: e.target.value as LayoutOption })}
        >
          <option value="list">List</option>
          <option value="compact_grid">Compact grid</option>
        </select>
      </div>

      <div className="forge-docgroup-body">
        {!props.groupId ? (
          <p className="forge-docgroup-hint">Choose a group to list its documents.</p>
        ) : !selectedGroup ? (
          <p className="forge-docgroup-warn">
            <i className="ti ti-alert-triangle" aria-hidden />{' '}
            This group no longer exists — the block will be skipped at publish.
          </p>
        ) : sorted.length === 0 ? (
          <p className="forge-docgroup-hint">
            '{selectedGroup.name}' has no documents — this block will be skipped at publish.
          </p>
        ) : (
          <>
            {preview.map((m) => (
              <div key={m.slug} className="forge-docgroup-row">
                <span className="forge-docgroup-title">{m.title}</span>
                {m.year_display && (
                  <span className="forge-docgroup-years">{m.year_display}</span>
                )}
              </div>
            ))}
            {overflow > 0 && (
              <p className="forge-docgroup-more">+{overflow} more</p>
            )}
          </>
        )}
      </div>

      {props.sort === 'manual' && selectedGroup && (
        <p className="forge-docgroup-footer">Manual order follows the Library.</p>
      )}
    </div>
  )
}
