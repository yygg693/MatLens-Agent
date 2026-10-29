import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import type { MemoryItem, MemoryListResponse } from '@/types/matlens'

const listMemories = vi.fn()
const getMemoryContentStatus = vi.fn()
const getMemoryLastInjection = vi.fn()
const addMemoryContent = vi.fn()
const updateMemoryContent = vi.fn()
const deleteMemoryContent = vi.fn()

vi.mock('@/matlens', () => ({
  addMemoryContent: (content: string) => addMemoryContent(content),
  deleteMemoryContent: (id: string) => deleteMemoryContent(id),
  getMemoryContentStatus: () => getMemoryContentStatus(),
  getMemoryLastInjection: () => getMemoryLastInjection(),
  listMemories: (params: unknown) => listMemories(params),
  updateMemoryContent: (id: string, text: string) => updateMemoryContent(id, text)
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

import { MemoryView } from './index'

function item(over: Partial<MemoryItem> = {}): MemoryItem {
  return {
    category: '材料',
    confidence: 0.9,
    created_at: '2026-10-20T10:00:00',
    id: 'm-1',
    memory: '[材料] NCM811 的循环衰减分析',
    metadata: {},
    score: 0,
    source_ref: null,
    source_type: 'user',
    updated_at: null,
    ...over
  }
}

function listWith(memories: MemoryItem[], over: Partial<MemoryListResponse> = {}): MemoryListResponse {
  return {
    count: memories.length,
    has_more: false,
    limit: 40,
    memories,
    mode: 'browse',
    offset: 0,
    ok: true,
    query: '',
    total: memories.length,
    ...over
  }
}

function renderView() {
  return render(
    <I18nProvider configClient={null} initialLocale="en">
      <MemoryView onClose={() => {}} />
    </I18nProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listMemories.mockResolvedValue(listWith([]))
  getMemoryContentStatus.mockResolvedValue({
    auto_write: true,
    count: 42,
    enabled: true,
    graph_auto_build: true,
    ok: true,
    provider: 'mem0',
    source: 'oss'
  })
  getMemoryLastInjection.mockResolvedValue({
    available: false,
    count: 0,
    memories: [],
    ok: true
  })
})

afterEach(() => {
  cleanup()
})

describe('MemoryView', () => {
  it('browses the store at the memory-content router', async () => {
    renderView()

    await waitFor(() => expect(listMemories).toHaveBeenCalled())
    expect(listMemories.mock.calls[0][0]).toMatchObject({ limit: 40, offset: 0 })
  })

  it('shows the exact store-wide count', async () => {
    renderView()

    await waitFor(() => expect(screen.getByText(/42 memories/)).toBeTruthy())
  })

  it('renders a memory in the list', async () => {
    listMemories.mockResolvedValue(listWith([item()]))
    renderView()

    await waitFor(() => expect(screen.getByText(/NCM811/)).toBeTruthy())
    expect(screen.getByText('材料')).toBeTruthy()
  })

  it('shows the detail panel once a row is selected', async () => {
    listMemories.mockResolvedValue(listWith([item()]))
    renderView()

    await waitFor(() => expect(screen.getByText(/NCM811/)).toBeTruthy())
    fireEvent.click(screen.getByText(/NCM811/))

    await waitFor(() => expect(screen.getByText('ID')).toBeTruthy())
    expect(screen.getByText('m-1')).toBeTruthy()
    // Provenance and confidence live in the detail panel.
    expect(screen.getByText('User statement')).toBeTruthy()
    expect(screen.getByText(/confidence 90%/)).toBeTruthy()
  })

  it('flags a row that both recallers found', async () => {
    listMemories.mockResolvedValue(listWith([item({ rrf_score: 0.032 })]))
    renderView()

    await waitFor(() => expect(screen.getByText(/NCM811/)).toBeTruthy())
    fireEvent.click(screen.getByText(/NCM811/))

    await waitFor(() => expect(screen.getByText('both recallers')).toBeTruthy())
  })

  it('says the subsystem is off when it is disabled', async () => {
    getMemoryContentStatus.mockResolvedValue({
      auto_write: false,
      count: null,
      enabled: false,
      graph_auto_build: false,
      ok: true,
      provider: 'mem0',
      source: null
    })
    renderView()

    await waitFor(() => expect(screen.getByText('Memory is turned off')).toBeTruthy())
  })

  it('lists what the agent actually injected this turn', async () => {
    getMemoryLastInjection.mockResolvedValue({
      available: true,
      count: 1,
      memories: [item({ id: 'inj-1', memory: '用户偏好中文回复' })],
      ok: true
    })
    renderView()

    await waitFor(() => expect(screen.getByText(/Injected this turn/)).toBeTruthy())
    expect(screen.getByText(/用户偏好中文回复/)).toBeTruthy()
  })

  it('reloads with the search term once the debounce elapses', async () => {
    renderView()

    const input = screen.getByLabelText('Search memories')
    fireEvent.change(input, { target: { value: '固态电解质' } })

    await waitFor(
      () => {
        const calls = listMemories.mock.calls
        expect(calls[calls.length - 1][0]).toMatchObject({ q: '固态电解质' })
      },
      { timeout: 2000 }
    )
  })

  it('loads the next page when there is more', async () => {
    listMemories.mockResolvedValue(listWith([item()], { has_more: true, total: 100 }))
    renderView()

    await waitFor(() => expect(screen.getByLabelText('Load more')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('Load more'))

    await waitFor(() => {
      const calls = listMemories.mock.calls
      expect(calls[calls.length - 1][0]).toMatchObject({ offset: 40 })
    })
  })
})
