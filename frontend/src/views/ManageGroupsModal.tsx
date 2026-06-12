import { useEffect, useRef, useState } from 'react'
import { api, type GroupInfo } from '../api'

const PALETTE = [
  '#9c5a3c', '#b08a3e', '#5a7d5a', '#5e8c8c',
  '#4a6d8c', '#7d6a8f', '#8c4a5e', '#6b6b6b',
]

function ColorPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (c: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const fn = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [open])
  return (
    <div className="color-picker-wrap" ref={ref}>
      <button
        type="button"
        className="color-swatch-btn"
        style={{ background: value }}
        onClick={() => setOpen((o) => !o)}
        title="Choose colour"
      />
      {open && (
        <div className="color-popover">
          {PALETTE.map((c) => (
            <button
              key={c}
              type="button"
              className={`color-swatch-btn${c === value ? ' selected' : ''}`}
              style={{ background: c }}
              onClick={() => { onChange(c); setOpen(false) }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function ManageGroupsModal({
  onClose,
  onChanged,
}: {
  onClose: () => void
  onChanged: () => void
}) {
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [newName, setNewName] = useState('')
  const [newColor, setNewColor] = useState(PALETTE[0])
  const [error, setError] = useState('')

  const reload = () => api.groups().then(setGroups)
  useEffect(() => { reload() }, [])

  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', fn)
    return () => document.removeEventListener('keydown', fn)
  }, [onClose])

  const reorder = (ids: number[]) => {
    api.reorderGroups(ids).then(() => { reload(); onChanged() })
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ minWidth: 420 }}>
        <div className="modal-header">
          <span>Manage groups</span>
          <button type="button" className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {groups.length === 0 && <p className="muted">No groups yet.</p>}
          {groups.map((g, i) => (
            <GroupRow
              key={g.id}
              group={g}
              canMoveUp={i > 0}
              canMoveDown={i < groups.length - 1}
              onMoveUp={() => {
                const ids = groups.map((x) => x.id)
                ;[ids[i - 1], ids[i]] = [ids[i], ids[i - 1]]
                reorder(ids)
              }}
              onMoveDown={() => {
                const ids = groups.map((x) => x.id)
                ;[ids[i], ids[i + 1]] = [ids[i + 1], ids[i]]
                reorder(ids)
              }}
              onUpdated={() => { reload(); onChanged() }}
              onDeleted={() => { reload(); onChanged() }}
            />
          ))}
        </div>
        <div className="modal-footer">
          <input
            type="text"
            placeholder="New group name…"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') createGroup() }}
            style={{ flex: 1 }}
          />
          <ColorPicker value={newColor} onChange={setNewColor} />
          <button
            type="button"
            className="btn-primary"
            disabled={!newName.trim()}
            onClick={createGroup}
          >
            Create group
          </button>
          {error && <span className="inline-error">{error}</span>}
        </div>
      </div>
    </div>
  )

  function createGroup() {
    if (!newName.trim()) return
    api.createGroup(newName.trim(), newColor).then(
      () => { setNewName(''); reload(); onChanged() },
      (e) => setError(String(e).includes('409') ? 'Name already in use' : String(e)),
    )
  }
}

function GroupRow({
  group,
  canMoveUp,
  canMoveDown,
  onMoveUp,
  onMoveDown,
  onUpdated,
  onDeleted,
}: {
  group: GroupInfo
  canMoveUp: boolean
  canMoveDown: boolean
  onMoveUp: () => void
  onMoveDown: () => void
  onUpdated: () => void
  onDeleted: () => void
}) {
  const [name, setName] = useState(group.name)
  const [color, setColor] = useState(group.color)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const save = (n: string, c: string) => {
    api.updateGroup(group.id, { name: n, color: c }).then(onUpdated)
  }

  if (confirmDelete) {
    return (
      <div className="group-row confirm-row">
        <span>
          Delete &ldquo;{group.name}&rdquo;? Its {group.members.length} documents move to Ungrouped.
        </span>
        <button type="button" className="btn-danger" onClick={() => api.deleteGroup(group.id).then(onDeleted)}>
          Delete
        </button>
        <button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>
          Cancel
        </button>
      </div>
    )
  }

  return (
    <div className="group-row">
      <ColorPicker value={color} onChange={(c) => { setColor(c); save(name, c) }} />
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => save(name, color)}
        onKeyDown={(e) => { if (e.key === 'Enter') save(name, color) }}
        className="group-name-input"
      />
      <span className="group-member-count muted">({group.members.length})</span>
      <button type="button" className="icon-btn" disabled={!canMoveUp} onClick={onMoveUp} title="Move up">
        <i className="ti ti-arrow-up" />
      </button>
      <button type="button" className="icon-btn" disabled={!canMoveDown} onClick={onMoveDown} title="Move down">
        <i className="ti ti-arrow-down" />
      </button>
      <button type="button" className="icon-btn danger" onClick={() => setConfirmDelete(true)} title="Delete group">
        <i className="ti ti-trash" />
      </button>
    </div>
  )
}
