"""Code-level detectors: packages, modules, import graph, SDKs, frameworks."""
import os
import posixpath
import re

from .model import load_json, load_toml

LANG_BY_EXT = {
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".py": "Python", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift", ".dart": "Dart",
    ".scala": "Scala", ".ex": "Elixir", ".exs": "Elixir", ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".sql": "SQL", ".tf": "HCL",
    ".sh": "Shell", ".lua": "Lua", ".zig": "Zig",
}
JS_EXT = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"}
SOURCE_EXT = set(LANG_BY_EXT) - {".sql", ".tf", ".sh"}

MANIFESTS = {
    "package.json": "node", "pyproject.toml": "python", "setup.py": "python",
    "requirements.txt": "python", "go.mod": "go", "Cargo.toml": "rust", "pom.xml": "java",
    "build.gradle": "java", "build.gradle.kts": "java", "composer.json": "php",
    "Gemfile": "ruby", "mix.exs": "elixir", "pubspec.yaml": "dart", "Package.swift": "swift",
}
PM_FILES = {
    "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "package-lock.json": "npm", "bun.lockb": "bun",
    "bun.lock": "bun", "uv.lock": "uv", "poetry.lock": "poetry", "Pipfile.lock": "pipenv",
    "go.sum": "go modules", "Cargo.lock": "cargo", "composer.lock": "composer", "Gemfile.lock": "bundler",
    "turbo.json": "turborepo", "nx.json": "nx", "lerna.json": "lerna",
}

FRAMEWORKS = {
    # js
    "next": "Next.js", "nuxt": "Nuxt", "@remix-run/node": "Remix", "@sveltejs/kit": "SvelteKit",
    "astro": "Astro", "react": "React", "vue": "Vue", "svelte": "Svelte", "@angular/core": "Angular",
    "solid-js": "Solid", "react-native": "React Native", "expo": "Expo", "electron": "Electron",
    "express": "Express", "fastify": "Fastify", "@nestjs/core": "NestJS", "hono": "Hono", "koa": "Koa",
    "@trpc/server": "tRPC", "graphql": "GraphQL", "@apollo/server": "Apollo", "vite": "Vite",
    "tailwindcss": "Tailwind", "@prisma/client": "Prisma", "drizzle-orm": "Drizzle", "typeorm": "TypeORM",
    "@tanstack/react-query": "TanStack Query", "@tanstack/react-start": "TanStack Start",
    # python
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "starlette": "Starlette",
    "sqlalchemy": "SQLAlchemy", "celery": "Celery", "pydantic": "Pydantic", "langchain": "LangChain",
    "streamlit": "Streamlit",
    # go
    "github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo", "github.com/gofiber/fiber": "Fiber",
    "github.com/go-chi/chi": "chi", "gorm.io/gorm": "GORM",
    # others
    "aspnetcore": "ASP.NET Core", "rails": "Rails", "laravel/framework": "Laravel", "spring-boot": "Spring Boot", "actix-web": "Actix",
    "axum": "Axum", "phoenix": "Phoenix",
}

# import prefix -> (external id, label, category)
SDKS = [
    # payments / commerce
    ("stripe", "stripe", "Stripe", "payments"), ("@stripe/", "stripe", "Stripe", "payments"),
    ("github.com/stripe/stripe-go", "stripe", "Stripe", "payments"),
    ("@paypal/", "paypal", "PayPal", "payments"), ("@lemonsqueezy/", "lemonsqueezy", "Lemon Squeezy", "payments"),
    # BaaS
    ("@supabase/", "supabase", "Supabase", "baas"), ("supabase", "supabase", "Supabase", "baas"),
    ("firebase-admin", "firebase", "Firebase", "baas"), ("firebase", "firebase", "Firebase", "baas"),
    ("firebase_admin", "firebase", "Firebase", "baas"), ("convex", "convex", "Convex", "baas"),
    ("@clerk/", "clerk", "Clerk", "auth"), ("next-auth", "authjs", "Auth.js", "auth"),
    ("@auth/", "authjs", "Auth.js", "auth"), ("@auth0/", "auth0", "Auth0", "auth"),
    ("better-auth", "better-auth", "Better Auth", "auth"),
    # cloud SDKs
    ("@aws-sdk/client-s3", "aws-s3", "AWS S3", "storage"), ("@aws-sdk/client-dynamodb", "aws-dynamodb", "DynamoDB", "database"),
    ("@aws-sdk/lib-dynamodb", "aws-dynamodb", "DynamoDB", "database"), ("@aws-sdk/client-sqs", "aws-sqs", "AWS SQS", "queue"),
    ("@aws-sdk/client-sns", "aws-sns", "AWS SNS", "queue"), ("@aws-sdk/client-ses", "aws-ses", "AWS SES", "email"),
    ("@aws-sdk/client-eventbridge", "aws-eventbridge", "EventBridge", "queue"),
    ("@aws-sdk/client-secrets-manager", "aws-secrets", "Secrets Manager", "secret"),
    ("@aws-sdk/client-bedrock-runtime", "aws-bedrock", "AWS Bedrock", "ai"),
    ("@aws-sdk/", "aws", "AWS", "cloud"), ("aws-sdk", "aws", "AWS", "cloud"), ("boto3", "aws", "AWS", "cloud"),
    ("botocore", "aws", "AWS", "cloud"), ("github.com/aws/aws-sdk-go", "aws", "AWS", "cloud"),
    ("@google-cloud/storage", "gcs", "Cloud Storage", "storage"), ("@google-cloud/pubsub", "gcp-pubsub", "Pub/Sub", "queue"),
    ("@google-cloud/firestore", "firestore", "Firestore", "database"), ("@google-cloud/", "gcp", "Google Cloud", "cloud"),
    ("google.cloud", "gcp", "Google Cloud", "cloud"), ("cloud.google.com/go", "gcp", "Google Cloud", "cloud"),
    ("@azure/", "azure", "Azure", "cloud"), ("azure", "azure", "Azure", "cloud"),
    ("@vercel/blob", "vercel-blob", "Vercel Blob", "storage"), ("@vercel/kv", "redis", "Redis", "cache"),
    ("@vercel/postgres", "postgres", "PostgreSQL", "database"), ("cloudinary", "cloudinary", "Cloudinary", "storage"),
    ("uploadthing", "uploadthing", "UploadThing", "storage"),
    # AI
    ("openai", "openai", "OpenAI", "ai"), ("@anthropic-ai/sdk", "anthropic", "Anthropic", "ai"),
    ("anthropic", "anthropic", "Anthropic", "ai"), ("@google/generative-ai", "gemini", "Gemini", "ai"),
    ("@google/genai", "gemini", "Gemini", "ai"), ("google.generativeai", "gemini", "Gemini", "ai"),
    ("@ai-sdk/", "ai-sdk", "Vercel AI SDK", "ai"), ("@pinecone-database/", "pinecone", "Pinecone", "database"),
    ("pinecone", "pinecone", "Pinecone", "database"), ("replicate", "replicate", "Replicate", "ai"),
    ("@huggingface/", "huggingface", "Hugging Face", "ai"), ("groq-sdk", "groq", "Groq", "ai"),
    # data
    ("pg", "postgres", "PostgreSQL", "database"), ("postgres", "postgres", "PostgreSQL", "database"),
    ("@neondatabase/serverless", "postgres", "PostgreSQL (Neon)", "database"),
    ("psycopg2", "postgres", "PostgreSQL", "database"), ("psycopg", "postgres", "PostgreSQL", "database"),
    ("asyncpg", "postgres", "PostgreSQL", "database"), ("github.com/jackc/pgx", "postgres", "PostgreSQL", "database"),
    ("github.com/lib/pq", "postgres", "PostgreSQL", "database"),
    ("mysql2", "mysql", "MySQL", "database"), ("mysql", "mysql", "MySQL", "database"), ("pymysql", "mysql", "MySQL", "database"),
    ("@planetscale/database", "mysql", "MySQL (PlanetScale)", "database"),
    ("mongodb", "mongodb", "MongoDB", "database"), ("mongoose", "mongodb", "MongoDB", "database"),
    ("pymongo", "mongodb", "MongoDB", "database"), ("motor", "mongodb", "MongoDB", "database"),
    ("go.mongodb.org/mongo-driver", "mongodb", "MongoDB", "database"),
    ("@libsql/client", "turso", "Turso / libSQL", "database"), ("better-sqlite3", "sqlite", "SQLite", "database"),
    ("redis", "redis", "Redis", "cache"), ("ioredis", "redis", "Redis", "cache"), ("@upstash/redis", "redis", "Redis (Upstash)", "cache"),
    ("github.com/redis/go-redis", "redis", "Redis", "cache"), ("github.com/go-redis/redis", "redis", "Redis", "cache"),
    ("bullmq", "redis", "Redis", "cache"), ("bull", "redis", "Redis", "cache"),
    ("@elastic/elasticsearch", "elasticsearch", "Elasticsearch", "database"), ("elasticsearch", "elasticsearch", "Elasticsearch", "database"),
    ("meilisearch", "meilisearch", "Meilisearch", "database"), ("algoliasearch", "algolia", "Algolia", "saas"),
    ("@qdrant/", "qdrant", "Qdrant", "database"), ("qdrant_client", "qdrant", "Qdrant", "database"),
    # messaging
    ("kafkajs", "kafka", "Kafka", "queue"), ("confluent_kafka", "kafka", "Kafka", "queue"), ("kafka", "kafka", "Kafka", "queue"),
    ("github.com/segmentio/kafka-go", "kafka", "Kafka", "queue"), ("amqplib", "rabbitmq", "RabbitMQ", "queue"),
    ("pika", "rabbitmq", "RabbitMQ", "queue"), ("celery", "celery", "Celery broker", "queue"),
    ("@upstash/qstash", "qstash", "QStash", "queue"), ("inngest", "inngest", "Inngest", "queue"),
    ("@trigger.dev/", "triggerdev", "Trigger.dev", "queue"),
    # comms
    ("@sendgrid/", "sendgrid", "SendGrid", "email"), ("sendgrid", "sendgrid", "SendGrid", "email"),
    ("resend", "resend", "Resend", "email"), ("nodemailer", "smtp", "SMTP", "email"), ("postmark", "postmark", "Postmark", "email"),
    ("twilio", "twilio", "Twilio", "saas"), ("@slack/", "slack", "Slack", "saas"), ("slack_sdk", "slack", "Slack", "saas"),
    ("discord.js", "discord", "Discord", "saas"), ("telegraf", "telegram", "Telegram", "saas"),
    ("@mailchimp/", "mailchimp", "Mailchimp", "email"),
    # observability
    ("@sentry/", "sentry", "Sentry", "observability"), ("sentry_sdk", "sentry", "Sentry", "observability"),
    ("posthog-js", "posthog", "PostHog", "observability"), ("posthog-node", "posthog", "PostHog", "observability"),
    ("posthog", "posthog", "PostHog", "observability"), ("@datadog/", "datadog", "Datadog", "observability"),
    ("dd-trace", "datadog", "Datadog", "observability"), ("@opentelemetry/", "otel", "OpenTelemetry", "observability"),
    ("@vercel/analytics", "vercel-analytics", "Vercel Analytics", "observability"), ("mixpanel", "mixpanel", "Mixpanel", "observability"),
]
SDKS.sort(key=lambda t: -len(t[0]))

ENV_HINTS = [
    (r"^STRIPE_", "stripe"), (r"^(DATABASE|POSTGRES|PG|DB)_?(URL|HOST|URI)", "postgres"),
    (r"^POSTGRES", "postgres"), (r"^MYSQL", "mysql"), (r"^MONGO", "mongodb"), (r"^(REDIS|KV|UPSTASH_REDIS)", "redis"),
    (r"SUPABASE", "supabase"), (r"^FIREBASE", "firebase"), (r"^OPENAI", "openai"), (r"^ANTHROPIC", "anthropic"),
    (r"^(GEMINI|GOOGLE_GENERATIVE|GOOGLE_AI)", "gemini"), (r"^SENTRY", "sentry"), (r"POSTHOG", "posthog"),
    (r"^RESEND", "resend"), (r"^SENDGRID", "sendgrid"), (r"^TWILIO", "twilio"), (r"^CLERK", "clerk"),
    (r"^(NEXTAUTH|AUTH_SECRET)", "authjs"), (r"^AUTH0", "auth0"), (r"^AWS_", "aws"), (r"^S3_", "aws-s3"),
    (r"^(GCP|GOOGLE_CLOUD|GCLOUD)", "gcp"), (r"^AZURE", "azure"), (r"^CLOUDINARY", "cloudinary"),
    (r"^PINECONE", "pinecone"), (r"^KAFKA", "kafka"), (r"^(RABBIT|AMQP)", "rabbitmq"), (r"^SMTP", "smtp"),
    (r"^SLACK", "slack"), (r"^ALGOLIA", "algolia"), (r"^DATADOG|^DD_", "datadog"), (r"^QSTASH", "qstash"),
    (r"^INNGEST", "inngest"), (r"^TRIGGER_", "triggerdev"), (r"^LEMON", "lemonsqueezy"), (r"^PAYPAL", "paypal"),
    (r"^CONVEX", "convex"), (r"^TURSO|^LIBSQL", "turso"), (r"^UPLOADTHING", "uploadthing"), (r"^REPLICATE", "replicate"),
    (r"^GROQ", "groq"), (r"^ELASTIC", "elasticsearch"), (r"^MEILI", "meilisearch"), (r"^QDRANT", "qdrant"),
]
EXT_LABELS = {ext_id: (label, cat) for _, ext_id, label, cat in SDKS}

ENV_EXAMPLE_RE = re.compile(r"(^|/)\.env(\.[\w-]+)*\.(example|sample|template|dist|defaults)$|(^|/)env\.example$|(^|/)example\.env$")

JS_IMPORT_RES = [
    re.compile(r"""(?:^|[\s;])(?:import|export)\s+(?:type\s+)?[^'";]*?\bfrom\s*['"]([^'"\n]+)['"]""", re.M),
    re.compile(r"""(?:^|[\s;])import\s*['"]([^'"\n]+)['"]""", re.M),
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
]
PY_FROM_RE = re.compile(r"^\s*from\s+(\.*[\w\.]*)\s+import\s+([\w\s,\*\(\)]+)", re.M)
PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w\.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w\.]+(?:\s+as\s+\w+)?)*)", re.M)
GO_IMPORT_BLOCK_RE = re.compile(r"^import\s*\(\s*(.*?)\)", re.M | re.S)
GO_IMPORT_LINE_RE = re.compile(r'^import\s+(?:\w+\s+)?"([^"]+)"', re.M)


def ext_node(m, ext_id, evidence):
    label, cat = EXT_LABELS.get(ext_id, (ext_id, "saas"))
    kind = {"database": "database", "cache": "cache", "queue": "queue", "storage": "bucket"}.get(cat, "service")
    return m.node(f"ext:{ext_id}", label, layer="external", kind=kind, category=cat, evidence=evidence)


def match_sdk(spec):
    for prefix, ext_id, _, _ in SDKS:
        if spec == prefix or spec.startswith(prefix + "/") or (prefix.endswith("/") and spec.startswith(prefix)) \
                or spec.startswith(prefix + "."):
            return ext_id
    return None


class CodeScanner:
    def __init__(self, model, files, module_depth=2, max_modules=40):
        self.m = model
        self.files = files
        self.fileset = set(files)
        self.depth = module_depth
        self.max_modules = max_modules
        self.packages = {}  # dir -> info
        self.pkg_by_name = {}
        self.file_module = {}
        self.dir_module = {}
        self._mfp_cache = {}
        self.dirs = set()
        for f in files:
            d = posixpath.dirname(f)
            while d and d not in self.dirs:
                self.dirs.add(d)
                d = posixpath.dirname(d)

    def run(self):
        self._languages()
        self._packages()
        self._modules()
        self._drop_empty_root()
        self._imports()
        self._env()
        self._entrypoints()
        self.m.detectors.add("code")
        return self

    # ------------------------------------------------------------------
    def _languages(self):
        langs = self.m.stack["languages"]
        for f in self.files:
            ext = os.path.splitext(f)[1].lower()
            if ext in LANG_BY_EXT:
                langs[LANG_BY_EXT[ext]] = langs.get(LANG_BY_EXT[ext], 0) + 1
            base = posixpath.basename(f)
            if base in PM_FILES:
                self.m.stack["package_managers"].add(PM_FILES[base])

    def _packages(self):
        m = self.m
        dirs = {}
        for f in self.files:
            base = posixpath.basename(f)
            if base in MANIFESTS or base.endswith((".csproj", ".fsproj")):
                d = posixpath.dirname(f) or "."
                # skip fixtures / examples deep inside tests
                if re.search(r"(^|/)(test|tests|__tests__|fixtures|examples?|templates?)(/|$)", d) and d != ".":
                    continue
                dirs.setdefault(d, []).append(base)
        if "." not in dirs:
            dirs["."] = []
        for d, manifests in sorted(dirs.items()):
            info = {"dir": d, "manifests": manifests, "deps": set(), "name": None, "lang": None, "frameworks": set()}
            for man in manifests:
                info["lang"] = info["lang"] or MANIFESTS.get(man, "dotnet")
                self._read_manifest(d, man, info)
            info["name"] = info["name"] or (posixpath.basename(d) if d != "." else os.path.basename(m.root))
            for dep in info["deps"]:
                if dep in FRAMEWORKS:
                    info["frameworks"].add(FRAMEWORKS[dep])
            m.stack["frameworks"].update(info["frameworks"])
            self.packages[d] = info
            if info["name"]:
                self.pkg_by_name[info["name"]] = d
        multi = len(self.packages) > 1
        for d, info in self.packages.items():
            if d == "." and multi and not info["manifests"]:
                info["virtual"] = True
                continue
            ui_app = info["frameworks"] & {"React", "Vue", "Svelte", "Solid"} and \
                (set(info.get("scripts") or {}) & {"dev", "start", "build"}) and "Vite" in info["frameworks"]
            kind = "app" if ui_app or info["frameworks"] & {"Next.js", "Nuxt", "Remix", "SvelteKit", "Astro", "Angular",
                                                           "Expo", "React Native", "Electron", "Streamlit", "TanStack Start"} else \
                "service" if info["frameworks"] & {"Express", "Fastify", "NestJS", "Hono", "Koa", "Django", "Flask",
                                                     "FastAPI", "Gin", "Echo", "Fiber", "chi", "Rails", "Laravel",
                                                     "Spring Boot", "Actix", "Axum", "Phoenix", "ASP.NET Core"} else "package"
            label = info["name"].rstrip("/").split("/")[-1] if info.get("go_module") else info["name"]
            m.node(f"pkg:{d}", label, layer="code", kind=kind, path=d,
                   meta={"language": info["lang"], "frameworks": sorted(info["frameworks"]),
                         "manifests": info["manifests"]},
                   evidence=f"{d}/{info['manifests'][0]}" if info["manifests"] else None)
            # SDK deps declared in the manifest
            for dep in info["deps"]:
                ext = match_sdk(dep)
                if ext:
                    ext_node(m, ext, f"dependency {dep} in {d}")
        # internal package dependencies
        for d, info in self.packages.items():
            if info.get("virtual"):
                continue
            for dep in info["deps"]:
                if dep in self.pkg_by_name and self.pkg_by_name[dep] != d:
                    m.edge(f"pkg:{d}", f"pkg:{self.pkg_by_name[dep]}", "depends_on")
        m.detectors.add("packages")

    def _read_manifest(self, d, man, info):
        p = man if d == "." else f"{d}/{man}"
        text = self.m.read(p)
        if man == "package.json":
            j = load_json(text) or {}
            info["name"] = j.get("name") or info["name"]
            for k in ("dependencies", "devDependencies", "peerDependencies"):
                info["deps"].update((j.get(k) or {}).keys())
            info["scripts"] = j.get("scripts") or {}
            if j.get("workspaces"):
                self.m.stack["package_managers"].add("workspaces")
        elif man == "pyproject.toml":
            t = load_toml(text) or {}
            proj = t.get("project") or {}
            poetry = (t.get("tool") or {}).get("poetry") or {}
            info["name"] = proj.get("name") or poetry.get("name") or info["name"]
            for dep in proj.get("dependencies") or []:
                info["deps"].add(re.split(r"[\s<>=!~\[;]", dep, 1)[0].lower())
            info["deps"].update(k.lower() for k in (poetry.get("dependencies") or {}))
        elif man == "requirements.txt":
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "-")):
                    info["deps"].add(re.split(r"[\s<>=!~\[;]", line, 1)[0].lower())
        elif man == "go.mod":
            mm = re.search(r"^module\s+(\S+)", text, re.M)
            if mm:
                info["name"] = mm.group(1)
                info["go_module"] = mm.group(1)
            for dep in re.findall(r"^\s*([\w\.\-/]+\.[\w\-/\.]+)\s+v", text, re.M):
                info["deps"].add(dep)
                for fw in FRAMEWORKS:
                    if dep.startswith(fw):
                        info["deps"].add(fw)
        elif man == "Cargo.toml":
            t = load_toml(text) or {}
            info["name"] = (t.get("package") or {}).get("name") or info["name"]
            info["deps"].update((t.get("dependencies") or {}).keys())
        elif man == "composer.json":
            j = load_json(text) or {}
            info["name"] = j.get("name") or info["name"]
            info["deps"].update((j.get("require") or {}).keys())
        elif man == "Gemfile":
            info["deps"].update(re.findall(r"""^\s*gem\s+['"]([^'"]+)""", text, re.M))
        elif man.endswith((".csproj", ".fsproj")):
            info["name"] = info["name"] or man.rsplit(".", 1)[0]
            info["deps"].update(re.findall(r'<PackageReference\s+Include="([^"]+)"', text))
            if "Microsoft.NET.Sdk.Web" in text:
                info["deps"].add("aspnetcore")
        elif man in ("pom.xml", "build.gradle", "build.gradle.kts"):
            if "spring-boot" in text:
                info["deps"].add("spring-boot")
            mm = re.search(r"<artifactId>([^<]+)</artifactId>", text)
            if mm and man == "pom.xml":
                info["name"] = mm.group(1)

    def exists(self, path):
        return path in (".", "") or path in self.fileset or path in self.dirs

    def package_of(self, path):
        d = posixpath.dirname(path)
        while True:
            if d in self.packages and not self.packages[d].get("virtual"):
                return d
            if d in ("", "."):
                return "." if "." in self.packages and not self.packages["."].get("virtual") else None
            d = posixpath.dirname(d)

    def _drop_empty_root(self):
        """A monorepo root manifest with no own source is just workspace glue."""
        if len(self.packages) > 1 and "pkg:." in self.m.nodes and \
                not any(n.get("parent") == "pkg:." for n in self.m.nodes.values()):
            self.m.nodes.pop("pkg:.")
            self.packages["."]["virtual"] = True

    def _orphan_root(self):
        """Source files outside every package go into a synthetic root package."""
        root = self.packages["."]
        if root.get("virtual"):
            root["virtual"] = False
            self.m.node("pkg:.", f"{root['name']} (root)", layer="code", kind="package", path=".")
        return "."

    def _module_key(self, pkg, path, depth):
        rel = path if pkg == "." else path[len(pkg) + 1:]
        parts = rel.split("/")[:-1]
        prefix = []
        if parts and parts[0] in ("src", "source", "lib") and len(parts) > 1:
            prefix, parts = parts[:1], parts[1:]
        key = parts[:depth]
        mod_dir = "/".join(([pkg] if pkg != "." else []) + prefix + key)
        return mod_dir or ".", "/".join(key) or "(root)"

    def _modules(self):
        m = self.m
        by_pkg = {}
        for f in self.files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in SOURCE_EXT or ".d.ts" in f or f.endswith((".min.js", ".config.js", ".config.ts")):
                continue
            pkg = self.package_of(f)
            if pkg is None:
                pkg = self._orphan_root()
            by_pkg.setdefault(pkg, []).append(f)
        for pkg, files in by_pkg.items():
            depth = self.depth
            while depth > 1 and len({self._module_key(pkg, f, depth) for f in files}) > self.max_modules:
                depth -= 1
            counts = {}
            for f in files:
                mod_dir, label = self._module_key(pkg, f, depth)
                counts.setdefault((mod_dir, label), []).append(f)
            for (mod_dir, label), mfiles in counts.items():
                mid = f"mod:{mod_dir}"
                is_test = bool(re.search(r"(^|/)(tests?|__tests__|spec|e2e|cypress|playwright)(/|$)", label))
                m.node(mid, label, layer="code", kind="test" if is_test else "module", parent=f"pkg:{pkg}",
                       path=mod_dir, meta={"files": len(mfiles)})
                for f in mfiles:
                    self.file_module[f] = mid
                self.dir_module[mod_dir] = mid

    # ------------------------------------------------------------------
    def _tsconfig_paths(self, pkg):
        """Return list of (alias_prefix, [target_dir_prefixes]) for a JS package."""
        out = []
        for cand in ("tsconfig.json", "jsconfig.json", "tsconfig.base.json"):
            p = cand if pkg == "." else f"{pkg}/{cand}"
            if p not in self.fileset:
                continue
            j = load_json(self.m.read(p), jsonc=True) or {}
            co = j.get("compilerOptions") or {}
            base = posixpath.normpath(posixpath.join(pkg if pkg != "." else "", co.get("baseUrl") or "."))
            for alias, targets in (co.get("paths") or {}).items():
                a = alias.rstrip("*")
                ts = [posixpath.normpath(posixpath.join(base, t.rstrip("*"))) for t in targets]
                out.append((a, ts))
        if not out:
            out = [("@/", [posixpath.normpath(posixpath.join(pkg, "src"))]), ("~/", [posixpath.normpath(posixpath.join(pkg, "src"))])]
        return out

    def module_for_path(self, path):
        """Best module id for a repo-relative file or directory path."""
        if path.startswith("./"):
            path = path[2:]
        if path in self._mfp_cache:
            return self._mfp_cache[path]
        self._mfp_cache[path] = r = self._module_for_path(path)
        return r

    def _module_for_path(self, path):
        if path in self.file_module:
            return self.file_module[path]
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".vue", ".svelte"):
            if path + ext in self.file_module:
                return self.file_module[path + ext]
            if f"{path}/index{ext}" in self.file_module:
                return self.file_module[f"{path}/index{ext}"]
            if f"{path}/__init__.py" in self.file_module:
                return self.file_module[f"{path}/__init__.py"]
        d = path
        while d and d != ".":
            if d in self.dir_module:
                return self.dir_module[d]
            # any file under this dir
            d = posixpath.dirname(d)
        prefix = path.rstrip("/") + "/"
        for f, mid in self.file_module.items():
            if f.startswith(prefix):
                return mid
        return None

    def _imports(self):
        m = self.m
        alias_cache = {}
        py_roots = self._python_roots()
        go_mods = {info["go_module"]: d for d, info in self.packages.items() if info.get("go_module")}
        for f, src_mod in self.file_module.items():
            ext = os.path.splitext(f)[1].lower()
            if ext not in JS_EXT and ext not in (".py", ".go"):
                continue
            text = self.m.read(f)
            if not text:
                continue
            fdir = posixpath.dirname(f)
            pkg = self.package_of(f)
            if ext in JS_EXT:
                specs = set()
                for rx in JS_IMPORT_RES:
                    specs.update(rx.findall(text))
                if pkg not in alias_cache:
                    alias_cache[pkg] = self._tsconfig_paths(pkg or ".")
                for spec in specs:
                    self._resolve_js(spec, f, fdir, src_mod, alias_cache[pkg])
            elif ext == ".py":
                specs = []
                for mod, names in PY_FROM_RE.findall(text):
                    specs.append((mod, [n.strip() for n in names.replace("(", "").replace(")", "").split(",")]))
                for group in PY_IMPORT_RE.findall(text):
                    for part in group.split(","):
                        specs.append((part.split(" as ")[0].strip(), []))
                for mod, names in specs:
                    self._resolve_py(mod, names, f, fdir, src_mod, py_roots)
            elif ext == ".go":
                specs = GO_IMPORT_LINE_RE.findall(text)
                for block in GO_IMPORT_BLOCK_RE.findall(text):
                    specs += re.findall(r'"([^"]+)"', block)
                for spec in specs:
                    ext_id = match_sdk(spec)
                    if ext_id:
                        ext_node(m, ext_id, f"import in {f}")
                        m.edge(src_mod, f"ext:{ext_id}", "uses")
                        continue
                    for gm, gdir in go_mods.items():
                        if spec == gm or spec.startswith(gm + "/"):
                            target = posixpath.normpath(posixpath.join(gdir, spec[len(gm):].lstrip("/")))
                            tm = self.module_for_path(target)
                            m.edge(src_mod, tm, "imports")
        m.detectors.add("imports")

    def _resolve_js(self, spec, f, fdir, src_mod, aliases):
        m = self.m
        target = None
        if spec.startswith("."):
            target = posixpath.normpath(posixpath.join(fdir, spec))
        else:
            for a, ts in aliases:
                if spec.startswith(a):
                    for t in ts:
                        cand = posixpath.normpath(posixpath.join(t, spec[len(a):]))
                        if self.module_for_path(cand):
                            target = cand
                            break
                    if target:
                        break
            if target is None:
                # workspace package?
                parts = spec.split("/")
                name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
                if name in self.pkg_by_name:
                    d = self.pkg_by_name[name]
                    if not self.packages[d].get("virtual"):
                        m.edge(src_mod, f"pkg:{d}", "imports")
                    return
                ext_id = match_sdk(spec)
                if ext_id:
                    ext_node(m, ext_id, f"import in {f}")
                    m.edge(src_mod, f"ext:{ext_id}", "uses")
                return
        tm = self.module_for_path(target)
        if tm and tm != src_mod:
            m.edge(src_mod, tm, "imports")

    def _python_roots(self):
        """Map top-level python package/module names to repo dirs."""
        roots = {}
        for f in self.files:
            if not f.endswith(".py"):
                continue
            parts = f.split("/")
            # find the outermost dir that is a package (has __init__.py) chain
            for i in range(len(parts) - 1):
                d = "/".join(parts[: i + 1])
                if f"{d}/__init__.py" in self.fileset:
                    parent = "/".join(parts[:i])
                    roots.setdefault(parts[i], parent)
                    break
            else:
                if len(parts) <= 3:  # top-level module files like app.py / src/app.py
                    roots.setdefault(parts[-1][:-3], "/".join(parts[:-1]))
        return roots

    def _resolve_py(self, mod, names, f, fdir, src_mod, roots):
        m = self.m
        if mod.startswith("."):
            dots = len(mod) - len(mod.lstrip("."))
            base = fdir
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            rest = mod.lstrip(".").replace(".", "/")
            target = posixpath.join(base, rest) if rest else base
            tm = self.module_for_path(target)
            if tm and tm != src_mod:
                m.edge(src_mod, tm, "imports")
            return
        top = mod.split(".")[0]
        if top in roots:
            target = posixpath.join(roots[top], mod.replace(".", "/")).lstrip("/")
            tm = self.module_for_path(target)
            if tm and tm != src_mod:
                m.edge(src_mod, tm, "imports")
            return
        ext_id = match_sdk(mod) or match_sdk(top)
        if ext_id:
            ext_node(m, ext_id, f"import in {f}")
            m.edge(src_mod, f"ext:{ext_id}", "uses")

    # ------------------------------------------------------------------
    def _env(self):
        """Read *keys only* from example env files (never real .env files)."""
        m = self.m
        for f in self.files:
            if not ENV_EXAMPLE_RE.search(f):
                continue
            keys = re.findall(r"^\s*(?:[a-z]+\s+)?([A-Z][A-Z0-9_]+)\s*=", m.read(f), re.M)
            if not keys:
                continue
            m.env_keys[f] = keys
            pkg = self.package_of(f)
            for k in keys:
                for rx, ext_id in ENV_HINTS:
                    if re.search(rx, k):
                        ext_node(m, ext_id, f"env {k} in {f}")
                        if pkg is not None:
                            m.edge(f"pkg:{pkg}", f"ext:{ext_id}", "configured")
                        break
        m.detectors.add("env")

    def _entrypoints(self):
        m = self.m
        for d, info in self.packages.items():
            if info.get("virtual"):
                continue
            eps = []
            scripts = info.get("scripts") or {}
            for k in ("start", "dev", "serve"):
                if k in scripts:
                    eps.append(f"npm {k}: {scripts[k]}")
            for cand in ("main.go", "cmd", "manage.py", "app.py", "main.py", "server.ts", "server.js",
                         "index.ts", "src/index.ts", "src/main.ts", "src/main.py", "src/server.ts", "app/page.tsx",
                         "app/layout.tsx", "src/app/layout.tsx", "pages/_app.tsx", "src/main.rs"):
                p = cand if d == "." else f"{d}/{cand}"
                if p in self.fileset or p in self.dirs:
                    eps.append(p)
            if eps:
                m.node(f"pkg:{d}", meta={"entrypoints": eps[:8]})
