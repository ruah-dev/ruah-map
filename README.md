# ruah

**See the architecture of any repo, code and cloud, right inside Claude Code.**

Type `/ruah:map` and a live map of your system opens above the prompt: packages and modules,
the services they call, the infrastructure they deploy to, and the CI that ships them. Claude
then explains it: what each part does, how requests flow through it, and where the risks are.

![The ruah map above the Claude Code prompt](media/screens/map.png)

## What you get

- **One command.** `/ruah:map` scans the repo locally in about a second, no model call needed for the map itself.
- **Code and cloud on one map.** Packages, modules and their imports next to Terraform, Kubernetes,
  Docker Compose, Cloudflare, Vercel, Netlify, Fly, Railway, Render, Firebase, Supabase and CI/CD.
- **Inside Claude Code.** The map lives in a band above the prompt or in a docked side panel
  (one click to move it, the choice is remembered). The terminal gets the same view as an outline.
- **Focus and flows.** Pick any component to light up everything it touches. `/ruah:map deep` has
  Claude trace the main flows step by step (checkout, sign-in, deploy…) and write up risks.
- **Drift, read-only.** `/ruah:map live aws` (or `gcp`, `azure`, `k8s`) compares what the repo
  declares with what is actually deployed, using list/describe calls only.

![A flow traced step by step](media/screens/flow.png)

## Install

In Claude Code:

```
/plugin marketplace add ruah-dev/ruah-map
/plugin install ruah@ruah
```

or from your shell:

```bash
claude plugin marketplace add ruah-dev/ruah-map
claude plugin install ruah@ruah
```

Requires `python3` (3.9+, standard library only). The in-app map panel is a Claude Code mod and
needs Claude Code 2.1.287 or later, where mods are on by default. On claude.ai and in Cowork the
`/ruah:map` skill works and shows the map as an Artifact.

## Commands

| Command | What it does |
|---|---|
| `/ruah:map` | Scan, add a short explanation, show the map |
| `/ruah:map code` · `/ruah:map infra` | Open on the Code or Infra view |
| `/ruah:map deep` | Full analysis: descriptions, code↔infra links, flows and risks |
| `/ruah:map live aws` | Add read-only cloud discovery and drift (`gcp`, `azure`, `k8s` too) |
| `/ruah:map md` | Also write a Mermaid `ARCHITECTURE.md` |
| `/ruah` | Instant map from the mod, no model call (`/ruah side`, `/ruah above`, `/ruah close`) |

![Docked beside the chat](media/screens/panel.png)

## What it reads, runs and sends

ruah is designed to keep your code on your machine.

- **Reads** the files of the repository you map. It never opens `.env` files, credentials,
  `*.tfstate` or private keys; from `.env.example`-style files it reads key names only.
- **Runs** `python3` scripts bundled in this plugin (`scripts/scan.py`, `scripts/render.py`) on your
  machine. They write their output to `<repo>/.ruah/`, which ignores itself in git.
- **Live mode only, and only when you ask for it** (`/ruah:map live aws|gcp|azure|k8s`): first runs one
  identity call with the CLI you already have (`aws sts get-caller-identity`, `gcloud config get-value project`,
  `az account show` or `kubectl config current-context`) so you can see which account will be read, and
  waits for your yes. Then it runs read-only list/describe calls with that same CLI. These calls use the
  credentials your CLI is already signed in with, on your machine; ruah never reads, prints or stores
  credential files or tokens. They are not pre-approved by the skill, so Claude Code asks you before each one.
- **Sends nothing anywhere by itself.** No telemetry, no external API calls. Claude reads the scan
  summary and the files it needs in your session, like any other task. If you ask for the map as a
  claude.ai Artifact, Claude publishes it privately to your account.
- **Optional HTML map** (`.ruah/architecture.html`) loads the cytoscape and ELK libraries from
  cdnjs.cloudflare.com and cdn.jsdelivr.net when you open it in a browser.

## The `/ruah` mod: what it runs, reads and submits

The in-app map is a Claude Code mod (`hooks/register.tsx`). It works on your machine only and
**sends nothing over the network**: no telemetry, no requests of its own.

**Hooks it adds**
- `session.start`: registers the `/ruah` command and the `show` tool (below), and restores where you
  last put the map (above the prompt or in the side panel) from the plugin's own store.
- `command.run` for `/ruah` only: scans and draws the map, or moves or closes it.
- `tool.call` for its own `mcp__ruah__show` tool only.
- `ui.render` for the `AbovePrompt` band (only while the map is open there; otherwise it passes the
  band through untouched) and for its own side panel.

It does not hook, wrap, block or stand in for any other tool, command or prompt. The `show` tool is
new and named `mcp__ruah__show`; it does not replace a built-in tool.

**Programs it runs:** only `python3`, with the two scripts bundled in this plugin, in the repository
you map. `/ruah` and the **Rescan** button run both; the `show` tool runs `render.py`, plus `scan.py` when asked to rescan:

```
python3 <plugin>/scripts/scan.py <repo>
python3 <plugin>/scripts/render.py <repo>/.ruah --pane --view <overview|code|infra|all>
```

`scan.py` reads the repository (same rules as above: no `.env`, credentials, `*.tfstate` or keys) and
writes `<repo>/.ruah/model.json`. `render.py` turns that into `<repo>/.ruah/pane.json`, the drawing.

**Files it reads and writes:** it reads `<repo>/.ruah/pane.json`. The scripts write only inside
`<repo>/.ruah/`. It also reads the app's theme setting (light or dark) to color the map, and keeps one
value in its store: `place` (`band` or `pane`).

**Prompts it submits:** only when you ask for an analysis, with `/ruah deep`, `/ruah live <provider>` or
`/ruah md`, or the **Analyze** button on the map (same as `/ruah deep`), it submits this prompt to your session:

```
Use the ruah:map skill with arguments: <deep|live aws|md> <repo path>
When enrich.json is written, call the mcp__ruah__show tool with this path so the map refreshes.
```

Nothing else is added to your prompts, and no prompt is submitted on its own.

**The `show` tool** (`mcp__ruah__show`, inputs `path`, `view`, `rescan`) lets Claude refresh the map after
it writes `.ruah/enrich.json`. It redraws the map in the app and returns one line of text to Claude.

## What the scanner understands

| Area | Detected |
|---|---|
| Code | package.json, pyproject, requirements, go.mod, Cargo, Maven/Gradle, composer, Gemfile, .csproj; workspaces and monorepos; import graphs for JS/TS (incl. tsconfig paths), Python and Go; frameworks; entrypoints |
| External services | ~100 SDKs (Stripe, Supabase, Firebase, AWS/GCP/Azure, OpenAI/Anthropic/Gemini, Postgres/MySQL/Mongo/Redis, Kafka/RabbitMQ, Sentry/PostHog/Datadog, Resend/SendGrid/Twilio…) |
| Infrastructure as code | Terraform/OpenTofu, CloudFormation & SAM, Serverless Framework, AWS CDK and Pulumi (heuristic), Bicep |
| Containers | Dockerfiles, Docker Compose, Kubernetes (workloads, services, ingress, Istio), Helm |
| Platforms | Cloudflare Workers, Vercel, Netlify, Fly.io, Railway, Render, Heroku, Firebase, Supabase, App Runner, App Engine |
| Data | Prisma and Drizzle schemas |
| CI/CD | GitHub Actions, GitLab, CircleCI, Cloud Build, Azure Pipelines, Bitbucket |

## Sharing maps publicly

Add `<repo>/.ruah/redact.json` to replace names before the map is drawn, for demos and screenshots:

```json
{ "name": "atlas", "hide_git": true, "replace": { "MyCompany": "atlas" }, "patterns": [{ "pattern": "\\b\\d{1,3}(\\.\\d{1,3}){3}\\b", "replace": "<ip>" }] }
```

## Limits

- Import graphs cover JS/TS, Python and Go; other languages get structure and SDK detection only.
- CDK and Pulumi detection is heuristic, and Helm templates are not rendered.

## License

MIT © ruah-dev. Part of the [ruah](https://ruah.sh) toolkit for agentic development.
