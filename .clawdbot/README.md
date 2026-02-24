# clawdbot — Agent Swarm Orchestration for ZeroClaw

Lightweight orchestration layer that creates isolated git worktrees,
spawns coding agents (Claude Code or Codex), tracks task state in a JSON
registry, and checks PR/CI status via GitHub CLI.

## Prerequisites

- **bash** (4.0+)
- **git** (2.15+ for worktree support)
- **jq** — JSON processor (`apt-get install jq` / `brew install jq`)
- **gh** — GitHub CLI (`apt-get install gh` / `brew install gh`), authenticated
- **claude** or **codex** CLI — whichever agent you plan to use

## Quick Setup

```bash
# 1. Make scripts executable (from repo root)
chmod +x .clawdbot/scripts/*

# 2. Add to PATH (or create a symlink)
export PATH="$PWD/.clawdbot/scripts:$PATH"

# 3. Optionally set workspace location (default: ~/agent-swarm)
export AGENT_SWARM_HOME=~/agent-swarm
```

## Usage

You can run via script wrapper:

```bash
clawdbot <command> ...
```

Or via the Rust CLI:

```bash
zeroclaw clawdbot <command> ...
```

### Kick off from a technical brief

```bash
clawdbot kickoff <task-id> <brief-file> [agent-type]
```

This will:
1. Create the worktree + task registry entry
2. Build prompt content from the brief file
3. Spawn the selected agent immediately

### Create a task

```bash
clawdbot create <task-id> "<description>" [agent-type]
```

- `task-id`: alphanumeric + hyphens (e.g., `fix-auth-refresh`)
- `description`: what the agent should do
- `agent-type`: `claude` (default) or `codex`

This will:
1. Create a git worktree at `$AGENT_SWARM_HOME/worktrees/<task-id>`
2. Create a branch `feat/<task-id>`
3. Generate a prompt template at `.clawdbot/prompts/<task-id>.md`
4. Register the task as `queued` in `.clawdbot/registry/active-tasks.json`

**Example:**

```bash
clawdbot create fix-auth "Fix OAuth token refresh — tokens expire silently"
```

### Edit the prompt

Before spawning, edit the generated prompt to add acceptance criteria and
file scope:

```bash
$EDITOR .clawdbot/prompts/fix-auth.md
```

### Spawn an agent

```bash
clawdbot spawn <task-id>
```

This will:
1. Verify the task exists and worktree is present
2. Install dependencies if a lockfile is detected
3. Launch the selected agent CLI against the worktree
4. Log output to `.clawdbot/logs/<task-id>.log`
5. Update task status to `running`

The agent runs in the foreground by default. Set `CLAWDBOT_USE_TMUX=1` to
run in a detached tmux session instead.

### Check task status

```bash
clawdbot check
```

Runs the supervisor check on all `running` and `pr_open` tasks:
- Verifies task branch exists locally and on `origin`
- Queries GitHub for open PRs matching the task branch
- Checks CI status via `gh pr checks`
- Checks for merge conflicts and out-of-date (`BEHIND`) PR branches
- Optionally checks tmux session liveness (`CLAWDBOT_CHECK_TMUX=1`)
- Enforces screenshot requirement for UI changes
- Updates task status and writes notifications

Status transitions:
- `running` → `pr_open` (when PR is opened)
- `pr_open` → `done` (when CI passes and definition-of-done is met)
- `pr_open` → `failed` (when CI checks fail)
- `pr_open` → `blocked` (merge conflicts or missing screenshot)

### View status

```bash
# All tasks
clawdbot status

# Single task (detailed JSON)
clawdbot status fix-auth
```

### Validate registry

```bash
clawdbot validate
```

Checks the registry JSON structure, required fields, valid status values,
and no duplicate IDs.

## Directory Structure

```
.clawdbot/
├── README.md              ← this file
├── registry/
│   ├── active-tasks.json       ← single source of truth
│   └── active-tasks.schema.json
├── policies/
│   └── definition-of-done.md   ← what "done" means
├── prompts/                     ← per-task prompt files
│   └── <task-id>.md
├── logs/                        ← agent stdout/stderr logs
│   ├── <task-id>.log
│   └── notifications.log
└── scripts/
    ├── clawdbot              ← CLI dispatcher
    ├── create_task           ← create worktree + register task
    ├── kickoff_task          ← create from brief + spawn
    ├── spawn_agent           ← launch agent CLI
    ├── supervisor_check      ← check PR/CI status
    └── validate_registry     ← schema self-check
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_SWARM_HOME` | `~/agent-swarm` | Root workspace for worktrees |
| `AGENT_SWARM_MAX_PARALLEL` | `1` | Max concurrent agent processes |
| `CLAWDBOT_USE_TMUX` | `0` | Use tmux sessions for agents |
| `CLAWDBOT_CHECK_TMUX` | `0` | Fail running tasks when tracked tmux session is dead |
| `TELEGRAM_BOT_TOKEN` | unset | Optional Telegram bot token for ready notifications |
| `TELEGRAM_CHAT_ID` | unset | Optional Telegram chat id for ready notifications |

## End-to-End Example

```bash
# Setup
chmod +x .clawdbot/scripts/*
export PATH="$PWD/.clawdbot/scripts:$PATH"

# Create a task
clawdbot create fix-memory-leak "Fix the SQLite connection pool leak in memory backend"

# Edit the prompt with specific instructions
vim .clawdbot/prompts/fix-memory-leak.md

# Spawn Claude Code against the isolated worktree
clawdbot spawn fix-memory-leak

# (agent works, creates commits, pushes branch, opens PR)

# Check if the PR is ready
clawdbot check

# View all task statuses
clawdbot status
```

## Design Decisions

- **Bash over Node/Python**: Matches existing repo tooling (`dev/ci.sh`,
  `scripts/`), zero additional dependencies beyond `jq` and `gh`.
- **Single JSON registry**: Simple, atomic via temp-file-then-mv, easy to
  inspect and version-control.
- **Deterministic checks only**: No file watchers or agent terminal monitoring.
  Status is derived from git state and GitHub API.
- **Foreground by default**: No tmux/screen dependency required. Optional
  tmux support via env var for users who want detached sessions.
- **Secrets from env only**: No tokens stored in files.
