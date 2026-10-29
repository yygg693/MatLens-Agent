import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  addMemoryContent,
  deleteMemoryContent,
  getMemoryById,
  getMemoryContentStatus,
  getMemoryLastInjection,
  listMemories,
  updateMemoryContent
} from './matlens'

// The memory-content router lives at /api/memories — the dashboard already
// owns /api/memory for *provider* status, so the two cannot share a prefix.
describe('Memory content REST helpers', () => {
  let api: ReturnType<typeof vi.fn>

  beforeEach(() => {
    api = vi.fn().mockResolvedValue({})
    Object.defineProperty(window, 'matlensDesktop', {
      configurable: true,
      value: { api }
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, 'matlensDesktop')
  })

  it('browses the store at /api/memories with offset paging', async () => {
    await listMemories({ limit: 20, offset: 40 })

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/api/memories?offset=40&limit=20' })
    )
  })

  it('omits every query parameter when none is given', async () => {
    await listMemories()

    expect(api).toHaveBeenCalledWith(expect.objectContaining({ path: '/api/memories' }))
  })

  it('encodes the search term', async () => {
    await listMemories({ q: '固态电解质', limit: 10 })

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/api/memories?q=%E5%9B%BA%E6%80%81%E7%94%B5%E8%A7%A3%E8%B4%A8&limit=10' })
    )
  })

  it('reads the content status from the content router', async () => {
    await getMemoryContentStatus()

    expect(api).toHaveBeenCalledWith(expect.objectContaining({ path: '/api/memories/status' }))
  })

  it('reads the last injection from the content router', async () => {
    await getMemoryLastInjection()

    expect(api).toHaveBeenCalledWith(expect.objectContaining({ path: '/api/memories/last-injection' }))
  })

  it('fetches one memory by id', async () => {
    await getMemoryById('abc-123')

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/api/memories/abc-123' })
    )
  })

  it('encodes a memory id that needs escaping', async () => {
    await getMemoryById('a/b c')

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/api/memories/a%2Fb%20c' })
    )
  })

  it('adds a memory', async () => {
    await addMemoryContent('NCM811 的循环衰减分析')

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/api/memories',
        method: 'POST',
        body: { content: 'NCM811 的循环衰减分析' }
      })
    )
  })

  it('updates a memory', async () => {
    await updateMemoryContent('m-1', '改写后的内容')

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/api/memories/m-1',
        method: 'PATCH',
        body: { text: '改写后的内容' }
      })
    )
  })

  it('deletes a memory', async () => {
    await deleteMemoryContent('m-1')

    expect(api).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/api/memories/m-1', method: 'DELETE' })
    )
  })
})
