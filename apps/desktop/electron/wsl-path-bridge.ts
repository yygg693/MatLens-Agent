import { execFileSync } from 'node:child_process'
import fs from 'node:fs'

// Bridges WSL/POSIX paths into forms the *Windows host* can open, for the case
// where the desktop UI runs on Windows and the gateway runs inside WSL (remote
// mode). Only the Windows-side direction lives here: the native folder dialog's
// defaultPath and the fs read path. The reverse (whatever path the backend
// receives → POSIX) is handled once, gateway-side, in
// matlens_constants.translate_cwd_for_wsl_backend, so it stays picker-agnostic.

const IS_WINDOWS = process.platform === 'win32'
const WIN_DRIVE_RE = /^([A-Za-z]):[\\/]/
// `/mnt/c` and `/mnt/c/...` (drvfs default automount root).
const WSL_MOUNT_RE = /^\/mnt\/([a-z])(?:\/(.*))?$/i
// Where Windows records the installed WSL distributions. Reading it is a
// silent registry query — unlike `wsl.exe`, it never raises a system dialog.
const WSL_REGISTRY_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss'

type ExecSyncLike = (file: string, args: string[], options: any) => string | Buffer

let cachedDistro: null | string = null
let cachedUncBase: null | string = null

/**
 * Pick the default distro from `wsl.exe -l -q` output.
 *
 * `wsl.exe` emits UTF-16LE without a BOM unless `WSL_UTF8=1` (WSL >= 0.64), so
 * older builds leave NUL bytes between characters even when we ask for utf8 —
 * strip them defensively before splitting. The default distro is the first
 * (`*`-marked, decoration removed by `-q`) entry. See microsoft/WSL#4607.
 */
export function parseDefaultDistro(raw: string): null | string {
  return (
    String(raw || '')
      .replace(/\0/g, '')
      .split(/\r?\n/)
      .map(line => line.replace(/^\*?\s*/, '').trim())
      .find(Boolean) || null
  )
}

/**
 * WSL state as recorded in the registry: the default distribution and every
 * installed one.
 */
export interface WslRegistryInfo {
  defaultDistro: null | string
  distros: string[]
}

/**
 * Parse a full `reg query <Lxss> /s` dump into the default distro plus the
 * list of installed ones.
 *
 * The key holds `DefaultDistribution` (the GUID of the distro WSL launches)
 * and one subkey per distribution carrying its `DistributionName`:
 *
 *   HKEY_CURRENT_USER\...\Lxss
 *       DefaultDistribution    REG_SZ    {guid-1}
 *
 *   HKEY_CURRENT_USER\...\Lxss\{guid-1}
 *       DistributionName    REG_SZ    Ubuntu
 *
 * The GUID is the join key: the default is the name under that exact subkey,
 * not merely the first one listed.
 */
export function parseWslRegistry(raw: string): WslRegistryInfo {
  const lines = String(raw || '').split(/\r?\n/)
  let currentKey = ''
  let defaultGuid = ''
  const byGuid = new Map<string, string>()
  const names: string[] = []

  for (const line of lines) {
    if (/^HKEY_/i.test(line.trim())) {
      currentKey = line.trim()

      continue
    }

    const defaultMatch = /DefaultDistribution\s+REG_SZ\s+(.+?)\s*$/i.exec(line)
    if (defaultMatch) {
      // Stored as a braced GUID ({1234-…}); the subkey is matched on the bare
      // GUID, so normalize both sides the same way.
      const raw = defaultMatch[1].trim()
      defaultGuid = (raw.match(/\{([^}]+)\}/i)?.[1] ?? raw).toLowerCase()

      continue
    }

    const nameMatch = /DistributionName\s+REG_SZ\s+(.+?)\s*$/i.exec(line)
    if (nameMatch) {
      const name = nameMatch[1].trim()
      const guid = (currentKey.match(/\{([^}]+)\}/i)?.[1] ?? '').toLowerCase()
      if (guid) {
        byGuid.set(guid, name)
      }
      names.push(name)
    }
  }

  const defaultDistro = (defaultGuid && byGuid.get(defaultGuid)) || null

  return { defaultDistro, distros: names }
}

/**
 * WSL state read from the registry — never from `wsl.exe`.
 *
 * Calling `wsl.exe` at all is off-limits: on a host without the WSL optional
 * feature it raises a system dialog asking to enable the virtual machine
 * platform, and even where WSL *is* installed the first invocation wakes the
 * WSL runtime, which lets the Store update service fire `wsl.exe --update`
 * in the background — a second, equally unsolicited dialog. The registry
 * answers the same question silently, and `reg.exe` is an ordinary tool that
 * never triggers the optional-feature prompt.
 */
export function readWslRegistry(exec: ExecSyncLike = execFileSync as any): WslRegistryInfo {
  try {
    const out = exec('reg.exe', ['query', WSL_REGISTRY_KEY, '/s'], {
      encoding: 'utf8',
      timeout: 2000,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'ignore']
    })

    return parseWslRegistry(typeof out === 'string' ? out : String(out ?? ''))
  } catch {
    // No Lxss key → WSL is not installed (or has no distribution).
    return { defaultDistro: null, distros: [] }
  }
}

/**
 * Default WSL distro name (cached). Falls back to `Ubuntu`.
 *
 * `reg.exe` prints in the console's OEM code page, so a non-ASCII distro name
 * can come back as replacement characters; such a name cannot address a UNC
 * share, so it is discarded in favour of the `Ubuntu` default.
 */
export function resolveDefaultWslDistro(exec: ExecSyncLike = execFileSync as any): string {
  if (cachedDistro) {
    return cachedDistro
  }

  if (!IS_WINDOWS) {
    cachedDistro = 'Ubuntu'

    return cachedDistro
  }

  const { defaultDistro, distros } = readWslRegistry(exec)
  const usable = (name: null | string): null | string =>
    name && !name.includes('\uFFFD') && name.trim() ? name.trim() : null

  cachedDistro = usable(defaultDistro) || usable(distros[0]) || 'Ubuntu'

  return cachedDistro
}

/** Drop the memoized distro / UNC base (tests only). */
export function resetWslProbeCache(): void {
  cachedDistro = null
  cachedUncBase = null
}

// `\\wsl.localhost\<distro>` (Win11 / Win10 >= 21364) with a `\\wsl$\<distro>`
// fallback for older builds. Probed once; defaults to wsl.localhost.
function wslUncBase(distro: string): string {
  if (cachedUncBase) {
    return cachedUncBase
  }

  const modern = `\\\\wsl.localhost\\${distro}`
  const legacy = `\\\\wsl$\\${distro}`

  try {
    if (!fs.existsSync(modern) && fs.existsSync(legacy)) {
      cachedUncBase = legacy

      return cachedUncBase
    }
  } catch {
    // Network-path probe failed — prefer the modern form.
  }

  cachedUncBase = modern

  return cachedUncBase
}

/**
 * A WSL/POSIX path → a path the Windows host can open: `/mnt/c/...` → `C:\...`
 * (drvfs mount), any other absolute POSIX path → `\\wsl.localhost\<distro>\...`.
 * Non-absolute or already-Windows paths pass through.
 */
export function wslPosixToWindowsAccessible(posixPath: string, distro: string = resolveDefaultWslDistro()): string {
  const value = String(posixPath || '').trim()
  const normalized = value.replace(/\\/g, '/')

  if (!normalized.startsWith('/')) {
    return value
  }

  const mount = normalized.match(WSL_MOUNT_RE)

  if (mount) {
    const tail = (mount[2] || '').replace(/\//g, '\\')

    return tail ? `${mount[1].toUpperCase()}:\\${tail}` : `${mount[1].toUpperCase()}:\\`
  }

  const relative = normalized.replace(/^\/+/, '').replace(/\//g, '\\')

  return `${wslUncBase(distro)}\\${relative}`
}

/** Native folder dialog `defaultPath`: open a WSL cwd in the Windows picker. */
export function resolvePickerDefaultPath(
  defaultPath: string | undefined,
  distro: string = resolveDefaultWslDistro()
): string | undefined {
  if (!defaultPath) {
    return undefined
  }

  const value = String(defaultPath).trim()

  return value.startsWith('/') && !WIN_DRIVE_RE.test(value) ? wslPosixToWindowsAccessible(value, distro) : defaultPath
}

/** fs read path: on Windows, make a WSL cwd readable via its UNC / drive form. */
export function resolveLocalReadPath(dirPath: string, distro: string = resolveDefaultWslDistro()): string {
  const value = String(dirPath || '').trim()

  return IS_WINDOWS && value.startsWith('/') && !WIN_DRIVE_RE.test(value)
    ? wslPosixToWindowsAccessible(value, distro)
    : value
}
