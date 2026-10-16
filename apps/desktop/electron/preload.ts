import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('matlensDesktop', {
  getConnection: profile => ipcRenderer.invoke('matlens:connection', profile),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('matlens:connection:for', payload),
  revalidateConnection: () => ipcRenderer.invoke('matlens:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('matlens:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('matlens:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('matlens:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('matlens:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('matlens:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('matlens:window:openInTerminal', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('matlens:window:openInstance'),
  claimAmbientCue: key => ipcRenderer.invoke('matlens:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('matlens:wake-indicator:get'),
    setState: state => ipcRenderer.send('matlens:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('matlens:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('matlens:wake-indicator:state', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('matlens:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('matlens:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('matlens:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('matlens:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('matlens:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('matlens:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('matlens:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('matlens:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('matlens:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    open: request => ipcRenderer.invoke('matlens:hud:open', request),
    close: () => ipcRenderer.invoke('matlens:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('matlens:hud:ignore-mouse', ignore),
    moveBy: delta => ipcRenderer.send('matlens:hud:move-by', delta),
    setBounds: bounds => ipcRenderer.send('matlens:hud:set-bounds', bounds),
    setVibrancy: on => ipcRenderer.invoke('matlens:hud:vibrancy', on),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('matlens:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('matlens:hud:goto', listener)

      return () => ipcRenderer.removeListener('matlens:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('matlens:hud:changed', listener)

      return () => ipcRenderer.removeListener('matlens:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('matlens:hud:cursor', listener)

      return () => ipcRenderer.removeListener('matlens:hud:cursor', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('matlens:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('matlens:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('matlens:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('matlens:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('matlens:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('matlens:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('matlens:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('matlens:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('matlens:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('matlens:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('matlens:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('matlens:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('matlens:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('matlens:connection-config:test', payload),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('matlens:connections:list'),
    save: payload => ipcRenderer.invoke('matlens:connections:save', payload),
    remove: id => ipcRenderer.invoke('matlens:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('matlens:connections:set-primary', id),
    test: id => ipcRenderer.invoke('matlens:connections:test', id),
    // Fan out `matlens update` to every eligible registered connection.
    updateAll: () => ipcRenderer.invoke('matlens:connections:update-all'),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:connections:changed', listener)

      return () => ipcRenderer.removeListener('matlens:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('matlens:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('matlens:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('matlens:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('matlens:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('matlens:connection-config:oauth-logout', remoteUrl),
  // MatLens Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('matlens:cloud:status'),
    login: () => ipcRenderer.invoke('matlens:cloud:login'),
    logout: () => ipcRenderer.invoke('matlens:cloud:logout'),
    discover: org => ipcRenderer.invoke('matlens:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('matlens:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('matlens:profile:get'),
    set: name => ipcRenderer.invoke('matlens:profile:set', name)
  },
  api: request => ipcRenderer.invoke('matlens:api', request),
  notify: payload => ipcRenderer.invoke('matlens:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('matlens:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('matlens:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('matlens:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('matlens:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('matlens:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('matlens:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('matlens:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('matlens:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('matlens:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('matlens:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('matlens:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('matlens:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('matlens:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('matlens:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('matlens:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('matlens:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('matlens:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('matlens:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('matlens:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('matlens:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('matlens:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('matlens:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('matlens:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('matlens:keep-awake', on),
  setDisableF12: blocked => ipcRenderer.send('matlens:devtools:disable-f12', blocked),
  setPreviewShortcutActive: active => ipcRenderer.send('matlens:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('matlens:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('matlens:openPreviewInBrowser', url),
  fetchLinkTitle: url => ipcRenderer.invoke('matlens:fetchLinkTitle', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('matlens:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('matlens:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('matlens:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('matlens:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('matlens:zoom:get'),
    setPercent: percent => ipcRenderer.send('matlens:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:zoom:changed', listener)

      return () => ipcRenderer.removeListener('matlens:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('matlens:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('matlens:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('matlens:logs:renderer-error', report),
  readDir: dirPath => ipcRenderer.invoke('matlens:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('matlens:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('matlens:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('matlens:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('matlens:fs:desktopPluginsRoot'),
  agentPluginsRoot: () => ipcRenderer.invoke('matlens:fs:agentPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('matlens:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('matlens:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('matlens:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('matlens:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('matlens:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('matlens:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('matlens:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('matlens:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('matlens:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('matlens:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('matlens:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('matlens:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('matlens:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('matlens:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('matlens:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('matlens:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('matlens:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('matlens:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('matlens:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('matlens:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('matlens:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('matlens:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('matlens:git:review:prList', repoPath, branches, numbers),
      fetchPrComment: (repoPath, url) => ipcRenderer.invoke('matlens:git:review:fetchPrComment', repoPath, url),
      createPr: repoPath => ipcRenderer.invoke('matlens:git:review:createPr', repoPath)
    }
  },
  terminal: {
    cwd: id => ipcRenderer.invoke('matlens:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('matlens:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('matlens:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('matlens:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('matlens:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `matlens:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `matlens:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('matlens:close-preview-requested', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('matlens:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:open-updates', listener)

    return () => ipcRenderer.removeListener('matlens:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:deep-link', listener)

    return () => ipcRenderer.removeListener('matlens:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('matlens:deep-link-ready'),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:window-state-changed', listener)

    return () => ipcRenderer.removeListener('matlens:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('matlens:focus-session', listener)

    return () => ipcRenderer.removeListener('matlens:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:notification-action', listener)

    return () => ipcRenderer.removeListener('matlens:notification-action', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('matlens:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:backend-exit', listener)

    return () => ipcRenderer.removeListener('matlens:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:connection:applied', listener)

    return () => ipcRenderer.removeListener('matlens:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:power-resume', listener)

    return () => ipcRenderer.removeListener('matlens:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('matlens:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('matlens:power-battery', listener)

    return () => ipcRenderer.removeListener('matlens:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:boot-progress', listener)

    return () => ipcRenderer.removeListener('matlens:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('matlens:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('matlens:bootstrap:continue-local'),
  resetBootstrap: () => ipcRenderer.invoke('matlens:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('matlens:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('matlens:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('matlens:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('matlens:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('matlens:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('matlens:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('matlens:uninstall:summary'),
    run: mode => ipcRenderer.invoke('matlens:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('matlens:updates:check'),
    apply: opts => ipcRenderer.invoke('matlens:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('matlens:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('matlens:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('matlens:updates:progress', listener)

      return () => ipcRenderer.removeListener('matlens:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('matlens:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('matlens:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('matlens:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('matlens:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('matlens:found-in-page', listener)

    return () => ipcRenderer.removeListener('matlens:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('matlens:open-find-bar', listener)

    return () => ipcRenderer.removeListener('matlens:open-find-bar', listener)
  }
})
