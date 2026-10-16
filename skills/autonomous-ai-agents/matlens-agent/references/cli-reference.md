# MatLens CLI Reference

Live sources when anything looks stale: `matlens --help`, `matlens <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
matlens [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
matlens chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
matlens setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
matlens model                Interactive model/provider picker
matlens fallback [add|remove|list]  Fallback provider chain
matlens config [show|edit|get|set|unset|path|env-path|check|migrate]
matlens login / logout       OAuth sign-in / clear stored auth
matlens doctor [--fix]       Check dependencies and config
matlens status [--all]       Component status
```

### Tools & Skills

```
matlens tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

matlens skills list|browse|search QUERY|inspect ID
matlens skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
matlens skills config        Enable/disable skills per platform
matlens skills check|update|uninstall|publish PATH
matlens skills tap add REPO  Add a GitHub repo as a skill source
matlens bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
matlens mcp add NAME (--url or --command) | remove | list | test NAME
matlens mcp catalog | install NAME     Curated catalog install
matlens mcp configure NAME             Toggle tool selection
matlens mcp serve                      Run MatLens as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
matlens gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `matlens photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
matlens sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
matlens cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
matlens webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
matlens profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
matlens profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
matlens auth                 Interactive credential manager
matlens auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
matlens auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
matlens desktop / gui        Native desktop app
matlens dashboard            Web admin panel + embedded chat (--stop / --status)
matlens proxy                OpenAI-compatible local proxy backed by an OAuth provider
matlens portal               Quick setup / sign in via Nous Portal
matlens kanban <verb>        Multi-agent work-queue board
matlens project              Named multi-folder workspaces
matlens skin list|use|set    Switch/tweak skins (see references/themes.md)
matlens pets <verb>          Pet mascots (see references/petdex.md)
matlens memory setup|status|off|reset   Memory provider
matlens secrets bitwarden|onepassword   External secret stores
matlens moa                  Mixture-of-Agents slots
matlens hooks / security / backup / import / checkpoints / console
matlens logs [-f] [errors]   View agent/error logs
matlens send                 One-off message through a gateway platform
matlens pairing / plugins / insights / journey / computer-use
matlens acp                  ACP server (IDE integration)
matlens completion bash|zsh|fish
matlens update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `matlens photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `hermes config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `hermes tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `hermes skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `hermes model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `hermes config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.matlens/logs/gateway.log` (or `matlens logs`) |
| Sessions | `matlens sessions browse` (reads state.db) |
