---
sidebar_position: 2
---

# Profiles: Running Multiple Agents

Run multiple independent MatLens agents on the same machine — each with its own config, API keys, memory, sessions, skills, and gateway state.

## What are profiles?

A profile is a separate MatLens home directory. Each profile gets its own directory containing its own `config.yaml`, `.env`, `SOUL.md`, memories, sessions, skills, cron jobs, and state database. Profiles let you run separate agents for different purposes — a coding assistant, a personal bot, a research agent — without mixing up MatLens state.

:::caution Give every agent its own profile
Never point two agent processes at the same profile (the same MatLens home). Both write memory automatically, and each loads the other's writes into its system prompt at session start — so two writers on one home compound each other's state until it stops being anything you configured. Profiles exist exactly to prevent this; agents that need shared memory should use an [external memory provider](/user-guide/features/memory-providers) instead.
:::

When you create a profile, it automatically becomes its own command. Create a profile called `coder` and you immediately have `coder chat`, `coder setup`, `coder gateway start`, etc.

## Quick start

```bash
matlens profile create coder       # creates profile + "coder" command alias
coder setup                       # configure API keys and model
coder chat                        # start chatting
```

That's it. `coder` is now its own MatLens profile with its own config, memory, and state.

## Creating a profile

:::tip
Quickest setup: run `matlens setup --portal` inside the new profile to wire up models + tools at once. See [Nous Portal](/integrations/nous-portal).
:::

### Blank profile

```bash
matlens profile create mybot
```

Creates a fresh profile with bundled skills seeded. Run `mybot setup` to configure API keys, model, and gateway tokens.

If you plan to use this profile as a kanban worker (or want the kanban orchestrator to route work to it), pass `--description "<role>"` at create time so the orchestrator knows what it's good at:

```bash
matlens profile create researcher --description "Reads source code and external docs, writes findings."
```

You can also set or auto-generate the description later with `matlens profile describe` — see the [Kanban guide](./features/kanban#auto-vs-manual-orchestration) for the full routing model.

### Clone config only (`--clone`)

```bash
matlens profile create work --clone
```

Copies your current profile's `config.yaml`, `.env`, `SOUL.md`, and skills into the new profile. Same API keys, model, and capabilities, but fresh sessions and memory. Edit `~/.matlens/profiles/work/.env` for different API keys, or `~/.matlens/profiles/work/SOUL.md` for a different personality.

### Clone everything (`--clone-all`)

```bash
matlens profile create backup --clone-all
```

Copies **everything** — config, API keys, personality, all memories, skills, cron jobs, plugins. A complete working snapshot. Per-profile history is excluded (session history, `state.db`, `backups/`, `state-snapshots/`, `checkpoints/`) — these belong to the source profile and can reach tens of GB. For a full backup including history, use `matlens profile export` or `matlens backup` instead.

### Clone from a specific profile

```bash
matlens profile create work --clone-from coder
```

`--clone-from <source>` selects the source profile directly and implies a config/skills/SOUL clone. Combine it with `--clone-all` when you want a full copy of that source profile:

```bash
matlens profile create work-backup --clone-from coder --clone-all
```

:::tip Honcho memory + profiles
When Honcho is enabled, clone operations automatically create a dedicated AI peer for the new profile while sharing the same user workspace. Each profile builds its own observations and identity. See [Honcho -- Multi-agent / Profiles](./features/memory-providers.md#honcho) for details.
:::

## Using profiles

### Command aliases

Every profile automatically gets a command alias at `~/.local/bin/<name>`:

```bash
coder chat                    # chat with the coder agent
coder setup                   # configure coder's settings
coder gateway start           # start coder's gateway
coder doctor                  # check coder's health
coder skills list             # list coder's skills
coder config set model.default anthropic/claude-sonnet-4
```

The alias works with every matlens subcommand — it's just `matlens -p <name>` under the hood.

### The `-p` flag

You can also target a profile explicitly with any command:

```bash
matlens -p coder chat
matlens --profile=coder doctor
matlens chat -p coder -q "hello"    # works in any position
```

### Sticky default (`matlens profile use`)

```bash
matlens profile use coder
matlens chat                   # now targets coder
matlens tools                  # configures coder's tools
matlens profile use default    # switch back
```

Sets a default so plain `matlens` commands target that profile. Like `kubectl config use-context`.

### Knowing where you are

The CLI always shows which profile is active:

- **Prompt**: `coder ❯` instead of `❯`
- **Banner**: Shows `Profile: coder` on startup
- **`matlens profile`**: Shows current profile name, path, model, gateway status

## Profiles vs workspaces vs sandboxing

Profiles are often confused with workspaces or sandboxes, but they are different things:

- A **profile** gives MatLens its own state directory: `config.yaml`, `.env`, `SOUL.md`, sessions, memory, logs, cron jobs, and gateway state.
- A **workspace** or **working directory** is where terminal commands start. That is controlled separately by `terminal.cwd`.
- A **sandbox** is what limits filesystem access. Profiles do **not** sandbox the agent.

On the default `local` terminal backend, the agent still has the same filesystem access as your user account. A profile does not stop it from accessing folders outside the profile directory.

If you want a profile to start in a specific project folder, set an explicit absolute `terminal.cwd` in that profile's `config.yaml`:

```yaml
terminal:
  backend: local
  cwd: /absolute/path/to/project
```

Using `cwd: "."` on the local backend means "the directory MatLens was launched from", not "the profile directory".

Also note:

- `SOUL.md` can guide the model, but it does not enforce a workspace boundary.
- Changes to `SOUL.md` take effect cleanly on a new session. Existing sessions may still be using the old prompt state.
- Asking the model "what directory are you in?" is not a reliable isolation test. If you need a predictable starting directory for tools, set `terminal.cwd` explicitly.

## Running gateways

Each profile runs its own gateway as a separate process with its own bot token:

```bash
coder gateway start           # starts coder's gateway
assistant gateway start       # starts assistant's gateway (separate process)
```

### Different bot tokens

Each profile has its own `.env` file. Configure a different Telegram/Discord/Slack bot token in each:

```bash
# Edit coder's tokens
nano ~/.matlens/profiles/coder/.env

# Edit assistant's tokens
nano ~/.matlens/profiles/assistant/.env
```

### Safety: token locks

If two profiles accidentally use the same bot token, the second gateway will be blocked with a clear error naming the conflicting profile. Supported for Telegram, Discord, Slack, WhatsApp, and Signal.

### Persistent services

```bash
coder gateway install         # creates matlens-gateway-coder systemd/launchd service
assistant gateway install     # creates matlens-gateway-assistant service
```

Each profile gets its own service name. They run independently.

:::note Inside the official Docker image
Per-profile gateways are supervised by [s6-overlay](https://github.com/just-containers/s6-overlay) (PID 1 in the container), so `matlens profile create <name>` automatically registers an s6 service slot at `/run/service/gateway-<name>/`. `matlens -p <name> gateway start/stop/restart` dispatches to `s6-svc` instead of spawning a bare process — crashes are auto-restarted and `docker restart` preserves the previously-running set of gateways. See [Per-profile gateway supervision](/user-guide/docker#per-profile-gateway-supervision) for details.
:::

## Configuring profiles

Each profile has its own:

- **`config.yaml`** — model, provider, toolsets, all settings
- **`.env`** — API keys, bot tokens
- **`SOUL.md`** — personality and instructions

```bash
coder config set model.default anthropic/claude-sonnet-4
echo "You are a focused coding assistant." > ~/.matlens/profiles/coder/SOUL.md
```

If you want this profile to work in a specific project by default, also set its own `terminal.cwd`:

```bash
coder config set terminal.cwd /absolute/path/to/project
```

### From the dashboard

The [web dashboard](features/web-dashboard.md#managing-multiple-profiles)
is a machine-level surface that can manage **any** profile's config, API
keys, skills, MCPs, and model via the profile switcher in its sidebar — no
per-profile dashboard needed. `coder dashboard` routes to the machine
dashboard with the `coder` profile preselected. The dashboard's Chat tab
also follows the switcher, spawning a conversation under the selected
profile's home.

Note: "Set as active" on the dashboard's Profiles page is the sticky
default for **future CLI/gateway runs** (same as `matlens profile use`) —
to edit a profile from the dashboard, use the switcher instead.

## Updating

`matlens update` pulls code once (shared) and syncs new bundled skills to **all** profiles automatically:

```bash
matlens update
# → Code updated (12 commits)
# → Skills synced: default (up to date), coder (+2 new), assistant (+2 new)
```

User-modified skills are never overwritten.

## Managing profiles

```bash
matlens profile list           # show all profiles with status
matlens profile show coder     # detailed info for one profile
matlens profile rename coder dev-bot   # rename (updates alias + service)
matlens profile export coder   # pack into coder.tar.gz (shareable; keys stripped)
matlens profile import coder.tar.gz   # install an archive as a new profile
```

In chat, the same two live as `/export` and `/import` — and in the desktop app as **⌘K → Export/Import profile…**. See [Sharing a profile](#sharing-a-profile).

## Deleting a profile

```bash
matlens profile delete coder
```

This stops the gateway, removes the systemd/launchd service, removes the command alias, and deletes all profile data. You'll be asked to type the profile name to confirm.

Use `--yes` to skip confirmation: `matlens profile delete coder --yes`

:::note
You cannot delete the default profile (`~/.matlens`). To remove everything, use `matlens uninstall`.
:::

## Tab completion

```bash
# Bash
eval "$(matlens completion bash)"

# Zsh
eval "$(matlens completion zsh)"
```

Add the line to your `~/.bashrc` or `~/.zshrc` for persistent completion. Completes profile names after `-p`, profile subcommands, and top-level commands.

## How it works

Profiles use the `MATLENS_HOME` environment variable. When you run `coder chat`, the wrapper script sets `MATLENS_HOME=~/.matlens/profiles/coder` before launching matlens. Since 119+ files in the codebase resolve paths via `get_matlens_home()`, MatLens state automatically scopes to the profile's directory — config, sessions, memory, skills, state database, gateway PID, logs, and cron jobs.

This is separate from terminal working directory. Tool execution starts from `terminal.cwd` (or the launch directory when `cwd: "."` on the local backend), not automatically from `MATLENS_HOME`.

On host installs, tool subprocesses keep your real OS-user `HOME` by default so
existing CLI credentials under `~` keep working across profiles. Profile data is
isolated by `MATLENS_HOME`, not by changing `HOME`. Container backends still use
`{MATLENS_HOME}/home` for persistent tool state, and host users who need strict
per-profile tool config can opt in with `terminal.home_mode: profile`.

This means two things that are easy to mix up:

- `MATLENS_HOME` is the profile boundary. It controls MatLens config, `.env`,
  memory, sessions, skills, logs, cron jobs, gateway state, and other MatLens
  data.
- `HOME` is the operating-system/user home that external CLIs expect. On host
  installs, MatLens keeps it as the real user home by default so tools like
  `git`, `ssh`, `gh`, `az`, `npm`, Claude Code, and Codex find the same
  credentials they use in your normal shell.

The tradeoff is that host profiles share normal user-level CLI state by default.
If you need separate CLI identities per profile, set `terminal.home_mode:
profile` in that profile's `config.yaml`. In that mode MatLens launches tool
subprocesses with `HOME={MATLENS_HOME}/home`; you then need to initialize or link
the profile-specific `~/.ssh`, `~/.gitconfig`, `~/.config/gh`, cloud CLI auth,
Claude/Codex auth, npm state, and similar files inside that profile home.

MatLens also exposes `MATLENS_REAL_HOME` to subprocesses so scripts can still find
the actual account home when `home_mode: profile` is active.

The default profile is simply `~/.matlens` itself. No migration needed — existing installs work identically.

## Sharing a profile

A profile you built on one machine can go to another — your own workstation, a teammate's laptop, or the community. Two paths:

**Send a file.** `/export` packs the profile into one `.tar.gz` — skills, memory, persona, crons, plugins, settings, and (from the desktop) your theme and layout. API keys are stripped. The recipient runs `/import`.

```bash
# In chat, run /export, hand over the file, and they run /import on it
matlens profile export coder
matlens profile import ./coder.tar.gz --name coder
```

**Publish a distribution.** Package the profile as a **git repository** so recipients install it with one command and pull versioned updates later. Carries the SOUL, config, skills, cron jobs, and MCP connections; credentials, memories, and sessions stay per-machine.

```bash
# Install a whole agent from a git repo
matlens profile install github.com/you/research-bot --alias

# Update later when the author ships a new version (keeps your memories + .env)
matlens profile update research-bot
```

Use an export file for a one-time handoff or a move; use a distribution for an agent you'll keep shipping. See **[Profile Distributions: Share a Whole Agent](./profile-distributions.md)** for both — the comparison table, authoring, publishing, update semantics, and the security model.
