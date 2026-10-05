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

## For directory reviewers

Answers to each check the Claude plugin directory runs, with the code each one points at.

**`MOD_RUNS_PROCESS` / `MOD_PROCESS_COMMAND_COMPUTED`** (`hooks/register.tsx`, the two `$.process.run` calls in
`build()`). The mod runs exactly two programs, both `python3` with a script bundled in this plugin:

| Command | When | Why |
|---|---|---|
| `python3 <plugin>/scripts/scan.py <repo>` | `/ruah`, the Rescan button, or the `show` tool with `rescan: true` | Reads the repository's files and writes `<repo>/.ruah/model.json` |
| `python3 <plugin>/scripts/render.py <repo>/.ruah --pane --view <overview\|code\|infra\|all>` | after a scan, or when you change view | Turns the model into `<repo>/.ruah/pane.json`, the drawing the mod shows |

The program and script names are fixed text at the call. Only the paths vary: `<plugin>` is the plugin's
install folder (`$.plugin.root`) and `<repo>` is the folder you map (the session's working directory, or a
path you typed after `/ruah`). `<view>` is one of the four fixed names. The mod never runs any other program
and never passes `--live`, so it never calls a cloud CLI.

**`MOD_LOCAL_DATA_LEAVES` / `MOD_SESSION_DATA_LEAVES`.** Nothing leaves the machine. `scan.py` and `render.py`
use the Python standard library only and make no network calls (no `urllib`, `socket` or `http` imports;
check with `grep -rn "urllib\|socket\|http.client" scripts`). The only file the mod reads with `$.fs.read` is
`<repo>/.ruah/pane.json`, which its own scripts wrote; it is drawn on screen and never passed to a process,
a prompt or the network. The mod's `tool.call` hook reads only the inputs of its own tool (`path`, `view`,
`rescan`); it reads no conversation text.

**`MOD_DATA_LEAVES_BY_PROMPT`** (`hooks/register.tsx`, `analyzePrompt()`). The submitted prompt is fixed
text plus two values: the analysis you picked (`deep`, `live <provider>` or `md`) and the repository path.
It never contains file contents or anything read from `pane.json`. The full text is shown above under
"Prompts it submits".

**`MOD_ANSWERS_FOR_TOOL`** (`hooks/register.tsx`, `on('tool.call', { tool: 'mcp__ruah__show' })`). The hook
answers only `mcp__ruah__show`, the tool this same mod registers in `session.start`. That tool has no other
implementation, so the hook is its implementation; it does not stand in for, wrap or change any built-in or
third-party tool, and every other tool call never reaches it.

**`MCP_FORWARDS_CREDENTIAL_ENV`** (`scripts/ruah_lib/code.py`, `_env()`). The scanner does not read your
environment: it never calls `printenv`, `env`, `export -p` or `set`, and never reads `os.environ`. `_env()`
reads only the variable *names* written in example files such as `.env.example` (never `.env` itself) to
tell which services a project uses, for example `STRIPE_SECRET_KEY` means Stripe. Values are discarded.
Nothing sends data off the machine, so the two parts are unrelated. Live mode (`/ruah:map live aws`) runs
your own cloud CLI, read-only and only after you confirm, as described above.

**`UNREAD_ASSET_REFERENCED`.** The only images are `.claude-plugin/icon.png` and the five README screenshots
in `media/screens/`. Nothing in the plugin runs them; the README only displays them.

**`COMMAND_NAMES_MOD_FILE`.** No script, skill or agent reads or writes the mod's files in `hooks/`.

## Development

```bash
python3 tests/test_fixture.py                                  # scanner + renderer on tests/fixture
claude plugin validate . --strict
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test .       # mod test in tests/mod
```

## License

MIT © ruah-dev. Part of the [ruah](https://ruah.sh) toolkit for agentic development. Docs: [ruah.sh/docs/map](https://www.ruah.sh/docs/map) · [Privacy](https://www.ruah.sh/docs/map/privacy) · [Terms](https://www.ruah.sh/docs/map/terms) · [Support](https://github.com/ruah-dev/ruah-map/issues)
