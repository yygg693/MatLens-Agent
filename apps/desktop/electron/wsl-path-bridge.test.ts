import assert from 'node:assert/strict'

import { test } from 'vitest'

import { parseDefaultDistro, parseWslRegistry, resolveDefaultWslDistro, resolvePickerDefaultPath, resetWslProbeCache, wslPosixToWindowsAccessible } from './wsl-path-bridge'

test('parseDefaultDistro reads the first distro from clean utf-8 output', () => {
  assert.equal(parseDefaultDistro('Ubuntu\nDebian\n'), 'Ubuntu')
})

test('parseDefaultDistro survives UTF-16LE NUL bytes older wsl.exe leaves in (WSL#4607)', () => {
  // `wsl.exe -l -q` emits UTF-16LE without a BOM on builds that ignore
  // WSL_UTF8; decoded as utf8 that reads as NUL-interleaved text.
  const utf16ish = '\0U\0b\0u\0n\0t\0u\0\r\0\n\0D\0e\0b\0i\0a\0n\0'
  assert.equal(parseDefaultDistro(utf16ish), 'Ubuntu')
})

test('parseDefaultDistro strips the default-marker and blank lines', () => {
  assert.equal(parseDefaultDistro('\n* Ubuntu\nDebian\n'), 'Ubuntu')
  assert.equal(parseDefaultDistro('   \n\n'), null)
})

test('wslPosixToWindowsAccessible maps a drvfs mount to its Windows drive', () => {
  assert.equal(wslPosixToWindowsAccessible('/mnt/c/Users/alex', 'Ubuntu'), 'C:\\Users\\alex')
  assert.equal(wslPosixToWindowsAccessible('/mnt/d', 'Ubuntu'), 'D:\\')
})

test('wslPosixToWindowsAccessible maps an in-distro POSIX path to a UNC share', () => {
  assert.equal(wslPosixToWindowsAccessible('/home/alex/proj', 'Ubuntu'), '\\\\wsl.localhost\\Ubuntu\\home\\alex\\proj')
})

test('wslPosixToWindowsAccessible leaves non-absolute / already-Windows paths alone', () => {
  assert.equal(wslPosixToWindowsAccessible('C:\\Users\\alex', 'Ubuntu'), 'C:\\Users\\alex')
  assert.equal(wslPosixToWindowsAccessible('relative/dir', 'Ubuntu'), 'relative/dir')
})

test('resolvePickerDefaultPath bridges a WSL cwd but passes Windows paths and empties through', () => {
  assert.equal(resolvePickerDefaultPath('/home/alex', 'Ubuntu'), '\\\\wsl.localhost\\Ubuntu\\home\\alex')
  assert.equal(resolvePickerDefaultPath('C:\\proj', 'Ubuntu'), 'C:\\proj')
  assert.equal(resolvePickerDefaultPath(undefined, 'Ubuntu'), undefined)
})

test('parseWslRegistry joins DefaultDistribution with the matching DistributionName', () => {
  const raw = [
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss',
    '    DefaultDistribution    REG_SZ    {GUID-2}',
    '',
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-1}',
    '    DistributionName    REG_SZ    Ubuntu',
    '    BasePath    REG_SZ    \\\\wsl$\\Ubuntu',
    '',
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-2}',
    '    DistributionName    REG_SZ    Debian',
    ''
  ].join('\r\n')

  const info = parseWslRegistry(raw)

  assert.deepEqual(info.distros, ['Ubuntu', 'Debian'])
  // The default is the name under the GUID the registry points at — not the
  // first one listed.
  assert.equal(info.defaultDistro, 'Debian')
})

test('parseWslRegistry falls back to no default when the GUID has no name', () => {
  const raw = [
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss',
    '    DefaultDistribution    REG_SZ    {guid-9}',
    '',
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-1}',
    '    DistributionName    REG_SZ    Ubuntu',
    ''
  ].join('\r\n')

  const info = parseWslRegistry(raw)

  assert.equal(info.defaultDistro, null)
  assert.deepEqual(info.distros, ['Ubuntu'])
  assert.deepEqual(parseWslRegistry(''), { defaultDistro: null, distros: [] })
})

test('resolveDefaultWslDistro never runs wsl.exe — the registry is the only source', () => {
  // The regression this guards: `wsl.exe` raises a system dialog asking to
  // enable the virtual machine platform, and even where WSL is installed the
  // first call wakes the WSL runtime, which lets the Store update service
  // fire `wsl.exe --update` in the background — a second unsolicited dialog.
  resetWslProbeCache()

  const asked: string[] = []
  const exec = (file: string) => {
    asked.push(file)

    throw new Error('no Lxss key')
  }

  assert.equal(resolveDefaultWslDistro(exec as any), 'Ubuntu')
  assert.deepEqual(asked, ['reg.exe'], 'only reg.exe may be consulted')
})

test('resolveDefaultWslDistro prefers the registry default distribution', () => {
  resetWslProbeCache()

  const exec = () =>
    [
      'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss',
      '    DefaultDistribution    REG_SZ    {guid-2}',
      'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-1}',
      '    DistributionName    REG_SZ    Ubuntu',
      'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-2}',
      '    DistributionName    REG_SZ    Debian',
      ''
    ].join('\r\n')

  assert.equal(resolveDefaultWslDistro(exec as any), 'Debian')
})

test('resolveDefaultWslDistro discards a name the OEM code page mangled', () => {
  // reg.exe prints in the console code page, so a non-ASCII distro name can
  // arrive as replacement characters — it cannot address a UNC share.
  resetWslProbeCache()

  const exec = () =>
    [
      'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss',
      '    DefaultDistribution    REG_SZ    {guid-1}',
      'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss\\{guid-1}',
      '    DistributionName    REG_SZ    \uFFFD\uFFFD\uFFFD',
      ''
    ].join('\r\n')

  assert.equal(resolveDefaultWslDistro(exec as any), 'Ubuntu')
})
