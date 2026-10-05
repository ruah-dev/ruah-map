---
name: map
description: Map and show the architecture of a repository, covering code structure (packages, modules, imports, external services) AND cloud infrastructure (Terraform, CloudFormation/SAM, Serverless, CDK, Pulumi, Bicep, Kubernetes, Helm, Docker Compose, Cloudflare, Vercel, Netlify, Fly, Railway, Render, Heroku, Firebase, Supabase, CI/CD), as an interactive diagram opened right away. Use for "/ruah:map", "ruah map", "ruah arch", "show me the architecture", "architecture diagram", "map this repo", "how is this deployed", "what infra does this use", "onboard me to this codebase".
argument-hint: "arch | code | infra | deep | live <aws|gcp|azure|k8s> | refresh | md | quick | open   [path]"
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, Agent
---

# ruah map: show me the architecture

Arguments: `$ARGUMENTS`

**Be fast and quiet.** Ask no questions (live mode excepted). Show progress in at most one short
line per phase. The user typed one word and expects a diagram to appear.

## Subcommands

| arg | does |
|---|---|
| `arch` (default, also empty) | scan → light enrichment → render → **show** (Overview tab) |
| `code` / `infra` | same as `arch`, opens on the Code / Infra tab |
| `deep` | scan → full enrichment by the `ruah-analyst` agent (flows + insights) → show |
| `live aws` (or `gcp`, `azure`, `k8s`, comma-separated) | adds read-only cloud discovery + drift, then shows the Infra tab |
| `refresh` | rescan, keep and repair `.ruah/enrich.json`, show |
| `md` | `arch` + write `ARCHITECTURE.md` (Mermaid) at the repo root |
| `quick` | scan → render → show, no enrichment (seconds) |
| `open` | just show the existing map again (render `--artifact` from the existing model, then step 4), no rescan |

Any other token is the repo path (default: the current working directory, or the folder the user
selected in the app). Unknown words: treat as `arch`.

## Step 0: paths

```bash
S="${CLAUDE_PLUGIN_ROOT}/scripts"; [ -f "$S/scan.py" ] || S="$(cd "$(dirname "${CLAUDE_SKILL_DIR:-.}")/../scripts" 2>/dev/null && pwd)"
[ -f "$S/scan.py" ] || S="$(ls -d ~/.claude/plugins/cache/*/ruah/*/scripts 2>/dev/null | tail -1)"
[ -f "$S/scan.py" ] || S="$(dirname "$(find / -path '*ruah*/scripts/scan.py' -not -path '*/node_modules/*' 2>/dev/null | head -1)")"
echo "$S"
```

Requires `python3` (stdlib only). Output always goes to `<repo>/.ruah/` (self-gitignored).

## Step 1: scan

```bash
python3 "$S/scan.py" "<repo>"            # prints a compact summary; writes <repo>/.ruah/model.json
```

Read the printed summary; don't cat model.json on big repos (query it with `python3 -c` if needed).

**live:** first tell the user in one line which account/context will be read (run
`aws sts get-caller-identity` / `gcloud config get-value project` / `az account show` /
`kubectl config current-context`) and wait for a yes. Then add `--live <providers>` to the
scan (plus `--aws-region R` if they named one). List/describe calls only; never mutate cloud
state, never print credentials.

## Step 2: enrich (skip for `quick` and `open`)

Never open real `.env*` files, credentials, `*.tfstate` or keys. `.env.example`-style files are
fine (key names only).

**Light (default `arch`, `code`, `infra`, `md`, `live`):** stay under about 15 targeted file
reads. Read the README, the entrypoints of each app/service, and whatever is listed under "gaps
for enrichment". Then write `<repo>/.ruah/enrich.json` with:
- `summary`: 3–6 markdown lines covering what the system is, how it's split, where it runs, and how data flows
- `nodes`: `{id: {label?, role, description}}` for every package and every main infra resource
- `add_edges`: the code→infra links you can see (`deploys_to`, `publishes`, `reads`, `writes`, `calls`) plus `same_as` for duplicates (for example the SDK-detected `ext:postgres` and the RDS/Supabase DB)
- 1–3 `flows` and up to 3 `insights` only if they are obvious

**Deep (`deep`, or when the repo has more than ~300 source files or more than ~8 packages):**
delegate to the `ruah-analyst` agent, passing the repo path, the `.ruah/model.json` path and `$S`.
It writes enrich.json.

Schema (ids must be real model ids or ids you add in `add_nodes`):
```json
{"summary": "...",
 "nodes": {"pkg:apps/api": {"label": "Orders API", "role": "api", "description": "..."}},
 "add_nodes": [{"id": "ext:erp", "label": "Legacy ERP", "layer": "external", "kind": "service"}],
 "add_edges": [{"source": "mod:apps/api/app/services", "target": "tf:infra/aws_sqs_queue.orders", "kind": "publishes", "label": "OrderCreated"}],
 "remove_nodes": [],
 "flows": [{"name": "Checkout", "steps": ["pkg:apps/web", {"node": "pkg:apps/api", "note": "POST /orders"}]}],
 "insights": [{"title": "...", "severity": "info|warn|risk", "body": "...", "nodes": ["..."]}]}
```
Validate, then fix every id it reports: `python3 "$S/render.py" "<repo>/.ruah" --validate`

**refresh:** rescan, run `--validate`, delete or re-point entries with dead ids, and cover new gaps.

## Step 3: render

```bash
python3 "$S/render.py" "<repo>/.ruah" --artifact --pane --view <overview|code|infra>   # + --md "<repo>/ARCHITECTURE.md" for md
```
Use `--view infra` for `infra` and `live`, and `--view code` for `code`. This writes two files:
`architecture.html` (standalone page for a browser) and `artifact.html` (the same map as a fragment
for the Claude Artifact viewer, with no absolute paths and no download button).

## Step 4: show it inside the app (pick the first that applies)

0. **The `mcp__ruah__show` tool exists** (Claude Code with the ruah mod: terminal or desktop Code tab):
   call it with `path` set to the repo and `view` set to the view. It re-renders and opens the
   **ruah pane** inside the app (diagram, flows, insights). Nothing else to do; skip the Artifact.
1. **The `Artifact` tool exists** (Claude desktop app, Code tab, claude.ai): publish
   `<repo>/.ruah/artifact.html` with `icon: "map"` and a one-sentence `description` naming the repo.
   It opens in the app's side panel; no server, nothing left running. If it was already published
   in this conversation, publish the same path again (same URL, no `icon`). The page already meets the
   Artifact page contract (title, theme tokens, CDN allowlist), so do not edit it. If the tool asks
   for its design skill first, load it and publish unchanged. Mention that the artifact is private.
2. **A file-sending tool or outputs folder** (Claude app / Cowork): send `<repo>/.ruah/architecture.html`
   with `SendUserFile` (`display: "render"`), or copy it into the outputs folder.
3. **Terminal CLI:** `python3 "$S/render.py" "<repo>/.ruah" --view <view> --open` opens the
   default browser.
4. Otherwise print the path.

Never start a local web server to show the map.

## Step 5: reply

Keep it short: 2–4 sentences on the architecture, the top insights if any, the path to
`.ruah/architecture.html`, and a hint such as "`/ruah deep` for flows and risks, `/ruah live aws` for
drift" (`/ruah:map deep` where the ruah mod is not installed). Don't paste JSON.
