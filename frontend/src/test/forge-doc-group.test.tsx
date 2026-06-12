/** M6 gate: ForgeDocGroupView tests. */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ForgeDocGroupView } from '../forge/ForgeDocGroupView'
import type { ForgeDocGroupProps } from '../forge/ForgeDocGroupView'
import { api } from '../api'
import type { GroupInfo } from '../api'

const GROUPS: GroupInfo[] = [
  {
    id: 1,
    name: 'The Memoirs',
    color: '#9c5a3c',
    sort_order: 0,
    members: [
      { slug: '1950-1960_early', title: 'Early Years', year_display: '1950–1960', standfirst: '', description: '', word_count: 1000, group_position: 0 },
      { slug: '1960-1970_middle', title: 'Middle Years', year_display: '1960–1970', standfirst: '', description: '', word_count: 2000, group_position: 1 },
      { slug: '1970-1980_later', title: 'Later Years', year_display: '1970–1980', standfirst: '', description: '', word_count: 3000, group_position: 2 },
    ],
  },
]

const defaultProps: ForgeDocGroupProps = {
  groupId: '',
  sort: 'manual',
  showBlurbs: true,
  showWordCounts: true,
  layout: 'list',
}

beforeEach(() => {
  vi.spyOn(api, 'groups').mockResolvedValue(GROUPS)
})

describe('ForgeDocGroupView', () => {
  it('shows chooser hint when groupId is empty', async () => {
    render(<ForgeDocGroupView props={defaultProps} />)
    await waitFor(() => expect(api.groups).toHaveBeenCalled())
    expect(screen.getByText(/Choose a group to list/i)).toBeInTheDocument()
  })

  it('shows member titles when a group is selected', async () => {
    render(<ForgeDocGroupView props={{ ...defaultProps, groupId: '1' }} />)
    await waitFor(() => expect(screen.getByText('Early Years')).toBeInTheDocument())
    expect(screen.getByText('Middle Years')).toBeInTheDocument()
    expect(screen.getByText('Later Years')).toBeInTheDocument()
  })

  it('calls onChange with groupId when select changes', async () => {
    const onChange = vi.fn()
    render(<ForgeDocGroupView props={defaultProps} onChange={onChange} />)
    await waitFor(() => expect(screen.getByLabelText('Choose group')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Choose group'), { target: { value: '1' } })
    expect(onChange).toHaveBeenCalledWith({ groupId: '1' })
  })

  it('shows "+N more" when over 5 members', async () => {
    const bigGroup: GroupInfo = {
      ...GROUPS[0],
      members: Array.from({ length: 7 }, (_, i) => ({
        slug: `1950-196${i}_doc-${i}`,
        title: `Doc ${i}`,
        year_display: '',
        standfirst: '',
        description: '',
        word_count: 100,
        group_position: i,
      })),
    }
    vi.spyOn(api, 'groups').mockResolvedValue([bigGroup])
    render(<ForgeDocGroupView props={{ ...defaultProps, groupId: '1' }} />)
    await waitFor(() => expect(screen.getByText('+2 more')).toBeInTheDocument())
  })

  it('shows warning text for missing group', async () => {
    render(<ForgeDocGroupView props={{ ...defaultProps, groupId: '999' }} />)
    await waitFor(() => expect(api.groups).toHaveBeenCalled())
    expect(screen.getByText(/no longer exists/i)).toBeInTheDocument()
  })

  it('patches showBlurbs via checkbox', async () => {
    const onChange = vi.fn()
    render(
      <ForgeDocGroupView props={{ ...defaultProps, groupId: '1', showBlurbs: true }} onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByLabelText('Choose group')).toBeInTheDocument())
    const checkbox = screen.getByLabelText('Blurbs')
    fireEvent.click(checkbox)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ showBlurbs: false }))
  })

  it('patches showWordCounts via checkbox', async () => {
    const onChange = vi.fn()
    render(
      <ForgeDocGroupView props={{ ...defaultProps, groupId: '1', showWordCounts: true }} onChange={onChange} />,
    )
    await waitFor(() => expect(screen.getByLabelText('Choose group')).toBeInTheDocument())
    const checkbox = screen.getByLabelText('Word counts')
    fireEvent.click(checkbox)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ showWordCounts: false }))
  })

  it('sorts members by date_range (ascending year)', async () => {
    const shuffled: GroupInfo = {
      ...GROUPS[0],
      members: [
        { slug: '1970-1980_later', title: 'Later Years', year_display: '1970–1980', standfirst: '', description: '', word_count: 0, group_position: 2 },
        { slug: '1950-1960_early', title: 'Early Years', year_display: '1950–1960', standfirst: '', description: '', word_count: 0, group_position: 0 },
        { slug: '1960-1970_middle', title: 'Middle Years', year_display: '1960–1970', standfirst: '', description: '', word_count: 0, group_position: 1 },
      ],
    }
    vi.spyOn(api, 'groups').mockResolvedValue([shuffled])
    render(<ForgeDocGroupView props={{ ...defaultProps, groupId: '1', sort: 'date_range' }} />)
    await waitFor(() => expect(screen.getByText('Early Years')).toBeInTheDocument())
    const titles = screen.getAllByText(/Years/)
    expect(titles[0].textContent).toBe('Early Years')
    expect(titles[1].textContent).toBe('Middle Years')
    expect(titles[2].textContent).toBe('Later Years')
  })

  it('shows manual-order footer when sort is manual', async () => {
    render(<ForgeDocGroupView props={{ ...defaultProps, groupId: '1', sort: 'manual' }} />)
    await waitFor(() => expect(screen.getByText(/Manual order follows the Library/i)).toBeInTheDocument())
  })
})
