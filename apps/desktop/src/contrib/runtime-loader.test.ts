import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { MatLensReadDirResult } from '@/global'
import type * as MatLensModule from '@/matlens'

import { $pluginRecords, setPluginEnabled } from './plugins-store'
import { discoverRuntimePlugins, watchRuntimePlugins } from './runtime-loader'

// getStatus would supply the connected backend's matlens_home — a REMOTE path in
// remote mode. The disk scanner must NOT derive the plugin root from it (#66899).
const getStatus = vi.fn(async () => ({ matlens_home: '/remote/box/.matlens' }))

vi.mock('@/matlens', async importActual => ({
  ...(await importActual<typeof MatLensModule>()),
  getStatus: () => getStatus()
}))

const desktopPluginsRoot = vi.fn<() => Promise<string>>()
const agentPluginsRoot = vi.fn<() => Promise<string>>()
const readDir = vi.fn<(path: string) => Promise<MatLensReadDirResult>>()
const readFileText = vi.fn<(path: string) => Promise<{ text: string }>>()
const watchDirectory = vi.fn<(path: string) => Promise<{ id: string }>>()
const watchPreviewFile = vi.fn<(path: string) => Promise<{ id: string }>>()
const onPreviewFileChanged = vi.fn()

beforeEach(() => {
  desktopPluginsRoot.mockReset()
  agentPluginsRoot.mockReset()
  readDir.mockReset()
  readFileText.mockReset()
  watchDirectory.mockReset()
  watchPreviewFile.mockReset()
  onPreviewFileChanged.mockReset()
  getStatus.mockClear()
  ;(window as unknown as { matlensDesktop: unknown }).matlensDesktop = {
    agentPluginsRoot,
    desktopPluginsRoot,
    onPreviewFileChanged,
    readDir,
    readFileText,
    watchDirectory,
    watchPreviewFile
  }
})

afterEach(() => {
  delete (window as unknown as { matlensDesktop?: unknown }).matlensDesktop
})

describe('scanDiskPlugins (#66899)', () => {
  it('scans the Electron-resolved local roots, never the backend matlens_home', async () => {
    desktopPluginsRoot.mockResolvedValue('/local/.matlens/desktop-plugins')
    agentPluginsRoot.mockResolvedValue('/local/.matlens/plugins')
    readDir.mockResolvedValue({ entries: [] })

    await discoverRuntimePlugins()

    expect(desktopPluginsRoot).toHaveBeenCalled()
    expect(readDir).toHaveBeenCalledWith('/local/.matlens/desktop-plugins')
    expect(readDir).toHaveBeenCalledWith('/local/.matlens/plugins')
    // The remote backend's matlens_home must never feed the local plugin scan.
    expect(getStatus).not.toHaveBeenCalled()
    expect(readDir).not.toHaveBeenCalledWith('/remote/box/.matlens/desktop-plugins')
  })

  it('no-ops when the resolvers yield no local root', async () => {
    desktopPluginsRoot.mockResolvedValue('')
    agentPluginsRoot.mockResolvedValue('')

    await discoverRuntimePlugins()

    expect(readDir).not.toHaveBeenCalled()
  })

  it('probes desktop/plugin.js inside agent-plugin packages (unified packaging)', async () => {
    desktopPluginsRoot.mockResolvedValue('/local/.matlens/desktop-plugins')
    agentPluginsRoot.mockResolvedValue('/local/.matlens/plugins')
    readDir.mockImplementation(async dir =>
      dir === '/local/.matlens/plugins'
        ? { entries: [{ isDirectory: true, name: 'my-feature', path: '/local/.matlens/plugins/my-feature' }] }
        : { entries: [] }
    )
    // No desktop half in this package — probe must target desktop/plugin.js.
    readFileText.mockRejectedValue(new Error('ENOENT'))

    await discoverRuntimePlugins()

    expect(readFileText).toHaveBeenCalledWith('/local/.matlens/plugins/my-feature/desktop/plugin.js')
    // The Python half's files must never be probed as a desktop entry.
    expect(readFileText).not.toHaveBeenCalledWith('/local/.matlens/plugins/my-feature/plugin.js')
  })

  it('still scans the standalone root when agentPluginsRoot is absent (older shell)', async () => {
    delete (window.matlensDesktop as unknown as { agentPluginsRoot?: unknown }).agentPluginsRoot
    desktopPluginsRoot.mockResolvedValue('/local/.matlens/desktop-plugins')
    readDir.mockResolvedValue({ entries: [] })

    await discoverRuntimePlugins()

    expect(readDir).toHaveBeenCalledWith('/local/.matlens/desktop-plugins')
    expect(readDir).toHaveBeenCalledTimes(1)
  })

  it('loads a unified desktop half OPT-IN: inventoried but not activated by default', async () => {
    desktopPluginsRoot.mockResolvedValue('/local/.matlens/desktop-plugins')
    agentPluginsRoot.mockResolvedValue('/local/.matlens/plugins')
    readDir.mockImplementation(async dir =>
      dir === '/local/.matlens/plugins'
        ? { entries: [{ isDirectory: true, name: 'uni', path: '/local/.matlens/plugins/uni' }] }
        : { entries: [] }
    )

    const register = vi.fn()

    ;(globalThis as unknown as { __uniRegister: unknown }).__uniRegister = register
    readFileText.mockResolvedValue({
      text: 'export default { id: "uni", register: globalThis.__uniRegister }'
    })
    watchPreviewFile.mockResolvedValue({ id: 'w-uni' })

    // The loader evaluates plugins via blob-URL import(), which vite's module
    // runner can't resolve in tests — reroute to a data: URL, which node's
    // native ESM loader handles.
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation(
        blob =>
          `data:text/javascript;base64,${Buffer.from((blob as unknown as { parts: string[] }).parts.join('')).toString('base64')}`
      )

    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const RealBlob = globalThis.Blob
    vi.stubGlobal(
      'Blob',
      class {
        parts: string[]
        constructor(parts: string[]) {
          this.parts = parts
        }
      }
    )

    try {
      await discoverRuntimePlugins()

      // Inventoried for Settings → Plugins, but the root's opt-in posture wins:
      // ~/.matlens/plugins stays installed-but-inert until the user toggles it.
      expect($pluginRecords.get().uni).toMatchObject({ kind: 'disk', status: 'disabled' })
      expect(register).not.toHaveBeenCalled()

      // The user's explicit enable still activates it.
      await setPluginEnabled('uni', true)
      expect(register).toHaveBeenCalledTimes(1)
      expect($pluginRecords.get().uni.status).toBe('loaded')
    } finally {
      createObjectURL.mockRestore()
      revokeObjectURL.mockRestore()
      vi.stubGlobal('Blob', RealBlob)
      delete (globalThis as unknown as { __uniRegister?: unknown }).__uniRegister
    }
  })
})

describe('watchRuntimePlugins dir watch (#66899)', () => {
  it('watches both Electron-resolved local roots, never the backend matlens_home', async () => {
    desktopPluginsRoot.mockResolvedValue('/local/.matlens/desktop-plugins')
    agentPluginsRoot.mockResolvedValue('/local/.matlens/plugins')
    readDir.mockResolvedValue({ entries: [] })
    watchDirectory.mockResolvedValue({ id: 'watch-1' })

    watchRuntimePlugins()
    // Drain the async scan + startDirWatches chains.
    await vi.waitFor(() => expect(watchDirectory).toHaveBeenCalledTimes(2))

    expect(watchDirectory).toHaveBeenCalledWith('/local/.matlens/desktop-plugins')
    expect(watchDirectory).toHaveBeenCalledWith('/local/.matlens/plugins')
    expect(watchDirectory).not.toHaveBeenCalledWith('/remote/box/.matlens/desktop-plugins')
    expect(getStatus).not.toHaveBeenCalled()
  })
})
