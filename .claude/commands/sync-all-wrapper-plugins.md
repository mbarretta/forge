# Sync All Wrapper Plugins with Upstream

Sync each wrapper plugin with its upstream source and open a PR for any changes. This skill is designed to run remotely — it clones each plugin repo fresh rather than relying on local paths.

## Prerequisites

- `gh` CLI must be authenticated (`gh auth status`)
- `git`, `go`, and `uv` must be available on PATH
- `GITHUB_TOKEN` env var set, or `gh` CLI auth covers private repos

## Plugin Registry

| Plugin name | GitHub repo | Has sync-upstream command |
|---|---|---|
| libraries-coverage | `mbarretta/libraries-coverage-plugin` | yes |
| sourcier-forge | `mbarretta/sourcier-forge` | yes |

## For Each Plugin

Process each plugin sequentially. For each one:

### Step 1 — Clone into a temp directory

```bash
WORK_DIR=$(mktemp -d)
gh repo clone <github-repo> "$WORK_DIR"
cd "$WORK_DIR"
```

Use `gh repo clone` so authentication is handled automatically for private repos.

### Step 2 — Read the sync instructions

Read `$WORK_DIR/.claude/commands/sync-upstream.md` in full before doing anything else.

### Step 3 — Check if sync is needed

Follow the "check if sync is needed" step from the plugin's sync-upstream.md. If the plugin is already up to date with upstream, clean up the temp dir, skip to the next plugin, and note it in the final report.

### Step 4 — Execute the sync

Working inside `$WORK_DIR`, follow all remaining steps in the plugin's sync-upstream.md exactly as written, including:
- Fetching upstream files (via `gh api` calls that are already in the sync-upstream.md)
- Overwriting local files
- Applying any fixups (module paths, imports, etc.)
- Running verification (build, tests)

If verification fails (build errors, test failures), clean up the temp dir, record the failure in the final report, and move on to the next plugin.

### Step 5 — Create a branch, commit, and open a PR

If verification passed and there are changes:

1. Create a branch: `git checkout -b sync/upstream-<YYYY-MM-DD>`
2. Stage only the files changed by the sync (not unrelated files)
3. Commit:
   ```
   chore: sync with upstream <upstream-sha>
   ```
   - Use the actual upstream SHA from the sync check step
   - One sentence only — no bullet points, no body, no Co-Authored-By
4. Push: `git push -u origin sync/upstream-<YYYY-MM-DD>`
5. Open a PR:
   - Title: `chore: sync <plugin-name> with upstream (<upstream-sha-short>)`
   - Body: include the `git diff --stat` output and a link to the upstream commit or file if available
   - Leave it open for human review — do not merge or auto-approve

### Step 6 — Clean up

```bash
rm -rf "$WORK_DIR"
```

Always clean up, even on failure.

## Final Report

After processing all plugins, output a summary:

```
Plugin Sync Summary — <date>
─────────────────────────────────────────
libraries-coverage  ✓ PR opened: <url>
                 OR ✓ Already in sync (sha: <sha>)
                 OR ✗ Failed: <reason>

sourcier-forge      ✓ PR opened: <url>
                 OR ✓ Already in sync (sha: <sha>)
                 OR ✗ Failed: <reason>
```

## Rules

- Process plugins sequentially to avoid resource conflicts
- Never push directly to `main` or `master`
- Never skip build or test verification — a broken sync is worse than no sync
- If a branch `sync/upstream-<date>` already exists on origin (PR already open for today), skip that plugin and note it in the report
- Always clean up temp dirs, even on failure
