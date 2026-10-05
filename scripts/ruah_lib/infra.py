"""Infrastructure detectors: IaC, containers, PaaS configs, CI/CD."""
import json
import os
import posixpath
import re

from . import yamlmini
from .code import ext_node
from .model import load_json, load_toml

# --------------------------------------------------------------------------
# Resource classification
# --------------------------------------------------------------------------
KIND_RULES = [
    (r"^(null_resource|terraform_data|time_sleep|time_|random_|local_|tls_|archive_|external$)", "binding"),
    (r"ServiceEntry|DestinationRule|PeerAuthentication|AuthorizationPolicy|Sidecar$", "network"),
    (r"event_source_mapping|lambda_permission|bucket_notification|event_target|topic_subscription|"
     r"integration$|integration_response|target_group_attachment|route$|stage$|deployment$|"
     r"eventarc_trigger|function_iam|EventSourceMapping|Permission$|Subscription$", "binding"),
    (r"iam|role|policy|service_account|role_assignment|access_policy|IAM::|ManagedPolicy|InstanceProfile", "iam"),
    (r"lambda_function$|cloudfunctions\d?_function|function_app|worker_script|workers_script|Lambda::Function|"
     r"Serverless::Function|cloud_run_v2_job|Microsoft\.Web/sites/functions|lambda\.Function|NodejsFunction|"
     r"PythonFunction|lambda\.DockerImageFunction", "function"),
    (r"s3_bucket$|storage_bucket$|storage_account$|r2_bucket|S3::Bucket$|s3\.Bucket|Microsoft\.Storage/storageAccounts$|"
     r"efs_file_system|filestore", "bucket"),
    (r"db_instance$|rds_cluster$|dynamodb_table$|sql_database_instance|sql_server|postgresql|mysql|cosmosdb|spanner|"
     r"bigtable|firestore|d1_database|docdb|neptune|redshift|bigquery_dataset|RDS::DB|DynamoDB::|Serverless::SimpleTable|"
     r"dynamodb\.Table|rds\.Database|Microsoft\.Sql|Microsoft\.DBfor|DocumentDB|opensearch|elasticsearch_domain", "database"),
    (r"elasticache|redis|memcache|memorystore|workers_kv|ElastiCache", "cache"),
    (r"sqs_queue$|sns_topic$|pubsub_topic$|pubsub_subscription|servicebus|eventhub|kinesis|msk_cluster|mq_broker|"
     r"cloudwatch_event_rule|event_bus|scheduler_schedule|SQS::Queue|SNS::Topic|Events::Rule|sqs\.Queue|sns\.Topic|"
     r"events\.Rule|queue$|cloud_scheduler|cloud_tasks|StepFunctions|sfn_state_machine|step_function", "queue"),
    (r"api_gateway|apigatewayv2_api|ApiGateway|Serverless::Api|Serverless::HttpApi|apigateway\.|lb$|alb$|elb$|"
     r"LoadBalancer|cloudfront|CloudFront|cdn|front_door|application_gateway|url_map|ingress|lb_listener$|Microsoft\.Cdn", "gateway"),
    (r"ecs_service$|ecs_cluster$|eks_cluster$|container_cluster$|cloud_run|app_service|web_app|container_app|"
     r"apprunner|elastic_beanstalk|app_engine|_instance$|compute_instance|virtual_machine|autoscaling_group|droplet|"
     r"ECS::Service|ECS::Cluster|EKS::Cluster|EC2::Instance|ecs\.|ecs_patterns|eks\.|ec2\.Instance|Microsoft\.Web/sites$|"
     r"Microsoft\.App/containerApps|Microsoft\.ContainerService|Microsoft\.Compute/virtualMachines", "compute"),
    (r"task_definition|TaskDefinition|ecr_repository|ECR::|artifact_registry|container_registry|helm_release|"
     r"kubernetes_|Microsoft\.ContainerRegistry", "container"),
    (r"route53|dns|cloudflare_record|cloudflare_zone|Route53::|route53\.|acm_certificate|certificate", "dns"),
    (r"vpc|subnet|security_group|network|nat_gateway|internet_gateway|route_table|firewall|peering|eip|vpn|"
     r"EC2::VPC|EC2::Subnet|SecurityGroup|ec2\.Vpc|Microsoft\.Network", "network"),
    (r"secret|kms|ssm_parameter|key_vault|SecretsManager|KMS::|SSM::Parameter|Microsoft\.KeyVault", "secret"),
    (r"cloudwatch|log_group|monitoring|logging|alarm|dashboard|application_insights|log_analytics|Logs::|CloudWatch::|"
     r"Microsoft\.Insights|Microsoft\.OperationalInsights", "observability"),
    (r"cognito|identity_platform|Cognito::|cognito\.", "auth"),
]
LOW_LEVEL = {"binding", "iam", "network", "observability", "secret"}


def classify(rtype):
    for rx, kind in KIND_RULES:
        if re.search(rx, rtype):
            return kind
    return "resource"


def platform_of(rtype):
    t = rtype.lower()
    for p in ("aws", "google", "azurerm", "azure", "cloudflare", "digitalocean", "kubernetes", "helm", "vercel",
              "github", "datadog", "fly", "heroku", "netlify", "supabase"):
        if t.startswith(p + "_") or t.startswith(p + "::") or t.startswith(p + "."):
            return {"google": "gcp", "azurerm": "azure"}.get(p, p)
    if t.startswith("microsoft."):
        return "azure"
    return None


PLATFORM_LABELS = {
    "aws": "AWS", "gcp": "Google Cloud", "azure": "Azure", "cloudflare": "Cloudflare", "vercel": "Vercel",
    "netlify": "Netlify", "fly": "Fly.io", "railway": "Railway", "render": "Render", "heroku": "Heroku",
    "firebase": "Firebase", "supabase": "Supabase", "kubernetes": "Kubernetes", "docker": "Docker",
    "digitalocean": "DigitalOcean", "github": "GitHub", "registry": "Container registry",
}

IMAGE_KINDS = [
    (r"postgres|postgis|timescale|cockroach", "database", "postgres"), (r"mysql|mariadb", "database", "mysql"),
    (r"mongo", "database", "mongodb"), (r"redis|valkey|keydb|dragonfly", "cache", "redis"),
    (r"memcached", "cache", None), (r"rabbitmq", "queue", "rabbitmq"), (r"kafka|redpanda|zookeeper", "queue", "kafka"),
    (r"nats", "queue", None), (r"elasticsearch|opensearch", "database", "elasticsearch"),
    (r"meilisearch", "database", "meilisearch"), (r"qdrant|weaviate|milvus|chroma", "database", None),
    (r"minio|localstack|azurite", "bucket", None), (r"nginx|traefik|caddy|haproxy|envoy", "gateway", None),
    (r"clickhouse|influx|prometheus|grafana|jaeger|otel|loki", "observability", None),
    (r"mailhog|mailpit", "service", None),
]


def image_kind(image):
    for rx, kind, ext in IMAGE_KINDS:
        if re.search(rx, image or "", re.I):
            return kind, ext
    return "compute", None


class InfraScanner:
    def __init__(self, model, files, code):
        self.m = model
        self.files = files
        self.fileset = set(files)
        self.code = code
        self.docker_dirs = {}  # dir -> dockerfile info

    def run(self):
        steps = [self._docker, self._terraform, self._cloudformation, self._serverless, self._cdk_pulumi,
                 self._bicep, self._kubernetes, self._compose, self._wrangler, self._paas, self._firebase,
                 self._supabase, self._prisma, self._ci]
        for step in steps:
            try:
                step()
            except Exception as e:  # a broken detector must not kill the scan
                self.m.warnings.append(f"{step.__name__}: {type(e).__name__}: {e}")
        return self

    # -- helpers -------------------------------------------------------
    def stack(self, sid, label, platform=None, kind="stack", file=None):
        return self.m.node(f"stack:{sid}", label, layer="infra", kind=kind, platform=platform, file=file)["id"]

    def res(self, rid, label, rtype, stack, platform=None, file=None, kind=None, meta=None):
        platform = platform or platform_of(rtype)
        k = kind or classify(rtype)
        return self.m.node(rid, label, layer="infra", kind=k, tech=rtype, parent=stack, platform=platform,
                           file=file, low_level=(k in LOW_LEVEL) or None, meta=meta)["id"]

    def link_code(self, path, infra_id, kind="deploys_to"):
        """Edge from the code module/package at `path` to an infra node."""
        if not path:
            return False
        path = posixpath.normpath(path)
        if path.startswith("..") or not self.code.exists(path):
            return False
        mid = self.code.module_for_path(path)
        if mid is None:
            pkg = self.code.package_of(path + "/x") if path != "." else "."
            mid = f"pkg:{pkg}" if pkg is not None and f"pkg:{pkg}" in self.m.nodes else None
        elif path in self.code.packages or path == ".":
            mid = f"pkg:{path}" if f"pkg:{path}" in self.m.nodes else mid
        if mid:
            self.m.edge(mid, infra_id, kind)
            return True
        return False

    def link_image(self, image, infra_id):
        if not image or not isinstance(image, str):
            return
        name = image.split("@")[0].rsplit(":", 1)[0] if "/" in image or ":" in image else image
        base = name.rstrip("/").split("/")[-1].lower()
        for d in self.docker_dirs:
            if posixpath.basename(d).lower() == base or (d == "." and base == self.m.nodes.get("pkg:.", {}).get("label", "").lower()):
                self.link_code(d, infra_id)
                return
        for pname, d in self.code.pkg_by_name.items():
            if pname.split("/")[-1].lower() == base and f"pkg:{d}" in self.m.nodes:
                self.m.edge(f"pkg:{d}", infra_id, "deploys_to")
                return

    def yaml_files(self, pred):
        for f in self.files:
            if f.endswith((".yml", ".yaml")) and pred(f):
                yield f

    # -- Docker ----------------------------------------------------------
    def _docker(self):
        for f in self.files:
            base = posixpath.basename(f)
            if not (base == "Dockerfile" or base.startswith("Dockerfile.") or base.endswith(".Dockerfile")):
                continue
            text = self.m.read(f)
            d = posixpath.dirname(f) or "."
            info = {"dockerfile": f,
                    "from": re.findall(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)", text, re.M | re.I)[:4],
                    "expose": re.findall(r"^\s*EXPOSE\s+(.+)$", text, re.M | re.I)[:4]}
            cmd = re.findall(r"^\s*(?:CMD|ENTRYPOINT)\s+(.+)$", text, re.M | re.I)
            if cmd:
                info["cmd"] = cmd[-1].strip()[:160]
            self.docker_dirs[d] = info
            pkg = self.code.package_of(f)
            if pkg is not None and f"pkg:{pkg}" in self.m.nodes:
                self.m.node(f"pkg:{pkg}", meta={"docker": info})
            self.m.detectors.add("docker")

    # -- Terraform / OpenTofu ---------------------------------------------
    def _terraform(self):
        by_dir = {}
        for f in self.files:
            if f.endswith((".tf", ".tofu")):
                by_dir.setdefault(posixpath.dirname(f) or ".", []).append(f)
        if not by_dir:
            return
        self.m.detectors.add("terraform")
        blocks_by_dir = {}
        for d, tf_files in by_dir.items():
            blocks = []
            for f in tf_files:
                text = self.m.read(f)
                for mm in re.finditer(r'^\s*(resource|data|module)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{', text, re.M):
                    body = _hcl_body(text, mm.end() - 1)
                    line = text.count("\n", 0, mm.start()) + 1
                    blocks.append((mm.group(1), mm.group(2), mm.group(3), body, f"{f}:{line}"))
            blocks_by_dir[d] = blocks
        for d, blocks in blocks_by_dir.items():
            if not blocks:
                continue
            sid = self.stack(f"tf:{d}", f"terraform · {d}", kind="stack", file=d)
            addr = {}  # "type.name" / "data.type.name" / "module.name" -> node id or ("data", body)
            data_bodies = {}
            for btype, a, b, body, loc in blocks:
                if btype == "resource":
                    nid = f"tf:{d}/{a}.{b}"
                    name = _hcl_literal(body, ("name", "bucket", "function_name", "table_name", "identifier",
                                                "cluster_identifier", "repository_name", "queue_name", "domain_name"))
                    self.res(nid, f"{b}", a, sid, file=loc, meta={"cloud_name": name, "type": a})
                    addr[f"{a}.{b}"] = nid
                elif btype == "data":
                    data_bodies[f"data.{a}.{b}"] = body
                elif btype == "module":
                    src = _hcl_literal(body, ("source",)) or ""
                    nid = f"tf:{d}/module.{a}"
                    self.m.node(nid, f"module {a}", layer="infra", kind="module", tech="terraform module",
                                parent=sid, file=loc, meta={"source": src})
                    addr[f"module.{a}"] = nid
                    if src.startswith("."):
                        target = posixpath.normpath(posixpath.join(d, src))
                        if target in blocks_by_dir:
                            self.m.edge(nid, f"stack:tf:{target}", "instantiates")
            ref_rx = re.compile(r"\b((?:data\.)?[a-z][a-z0-9]*_[a-z0-9_]+|module)\.([A-Za-z_][\w-]*)")

            def refs_of(body, depth=0):
                out = set()
                for t, n in ref_rx.findall(body):
                    key = f"{t}.{n}"
                    if key in addr:
                        out.add(addr[key])
                    elif key in data_bodies and depth < 2:
                        out |= refs_of(data_bodies[key], depth + 1)
                return out

            node_refs = {}
            for btype, a, b, body, loc in blocks:
                if btype == "data":
                    continue
                src = addr[f"{a}.{b}"] if btype == "resource" else addr[f"module.{a}"]
                node_refs[src] = refs_of(body)
                for r in node_refs[src]:
                    self.m.edge(src, r, "references")
                if btype == "resource":
                    self._tf_code_link(d, a, body, src, data_bodies)
                    self._tf_binding(a, body, addr, data_bodies)
            self._tf_iam_bridge(node_refs)

    def _tf_code_link(self, d, rtype, body, nid, data_bodies):
        paths = []
        for attr in ("source_dir", "source_file", "filename", "source_path", "working_dir", "context", "path", "entry", "main"):
            v = _hcl_literal(body, (attr,), raw=True)
            if v and (v.startswith('"') or "path." in v):
                paths.append(v)
        for key in re.findall(r"data\.(archive_file\.[\w-]+)", body):
            db = data_bodies.get(f"data.{key}", "")
            for attr in ("source_dir", "source_file"):
                v = _hcl_literal(db, (attr,), raw=True)
                if v:
                    paths.append(v)
        for p in paths:
            p = re.sub(r"\$\{path\.(module|root|cwd)\}|path\.(module|root|cwd)\s*,?", d + "/", p)
            p = p.replace("\"", "").replace("${", "").replace("}", "").strip()
            if p.endswith(".zip"):
                p = p[:-4]
            if self.link_code(posixpath.join(d, p) if not p.startswith(d) else p, nid):
                return

    BINDINGS = {
        "aws_lambda_event_source_mapping": ("event_source_arn", "function_name", "triggers"),
        "aws_lambda_permission": ("source_arn", "function_name", "invokes"),
        "aws_sns_topic_subscription": ("topic_arn", "endpoint", "triggers"),
        "aws_cloudwatch_event_target": ("rule", "arn", "triggers"),
        "aws_apigatewayv2_integration": ("api_id", "integration_uri", "routes_to"),
        "aws_api_gateway_integration": ("rest_api_id", "uri", "routes_to"),
        "aws_s3_bucket_notification": ("bucket", "lambda_function|queue|topic", "triggers"),
        "aws_lb_target_group_attachment": ("target_group_arn", "target_id", "routes_to"),
        "google_cloud_scheduler_job": ("name", "http_target|pubsub_target", "triggers"),
        "google_eventarc_trigger": ("matching_criteria", "destination", "triggers"),
    }

    def _tf_binding(self, rtype, body, addr, data_bodies):
        spec = self.BINDINGS.get(rtype)
        if not spec:
            return
        src_attr, dst_attr, kind = spec

        def refs(attr_rx):
            out = []
            for mm in re.finditer(rf"\b(?:{attr_rx})\s*(?:=|\{{)([^\n]*(?:\n\s+[^\n]*)?)", body):
                for t, n in re.findall(r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\.([A-Za-z_][\w-]*)", mm.group(1)):
                    if f"{t}.{n}" in addr:
                        out.append(addr[f"{t}.{n}"])
            return out
        for s in refs(src_attr):
            for t in refs(dst_attr):
                self.m.edge(s, t, kind)

    def _tf_iam_bridge(self, node_refs):
        """principal -> role <- policy -> target  ==>  principal --accesses--> target"""
        nodes = self.m.nodes
        roles = {nid for nid in node_refs if nodes[nid].get("kind") == "iam" and re.search(r"iam_role$|service_account$", nodes[nid].get("tech", ""))}
        if not roles:
            return
        principals = {}
        for nid, refs in node_refs.items():
            if nodes[nid].get("kind") in ("iam", "binding"):
                continue
            for r in refs & roles:
                principals.setdefault(r, set()).add(nid)
        for nid, refs in node_refs.items():
            if nodes[nid].get("kind") != "iam" or nid in roles:
                continue
            attached = refs & roles
            # a policy attachment points at a policy which points at targets
            targets = set()
            for r in refs:
                if nodes[r].get("kind") == "iam" and r not in roles:
                    targets |= {x for x in node_refs.get(r, ()) if nodes[x].get("kind") not in LOW_LEVEL}
                elif nodes[r].get("kind") not in LOW_LEVEL:
                    targets.add(r)
            for role in attached:
                for p in principals.get(role, ()):
                    for t in targets:
                        self.m.edge(p, t, "accesses")

    # -- CloudFormation / SAM --------------------------------------------
    def _cloudformation(self):
        cands = [f for f in self.files if f.endswith((".yml", ".yaml", ".json", ".template"))
                 and not f.endswith(("package.json", "tsconfig.json", "package-lock.json"))
                 and not posixpath.basename(f).startswith(("docker-compose", "compose."))
                 and "/.github/" not in "/" + f]
        for f in cands:
            text = self.m.read(f)
            if not re.search(r"AWSTemplateFormatVersion|Transform:\s*AWS::Serverless|\"Type\"\s*:\s*\"AWS::|^\s+Type:\s*AWS::", text, re.M):
                continue
            doc = load_json(text) if f.endswith(".json") else yamlmini.load(text)
            if not isinstance(doc, dict) or not isinstance(doc.get("Resources"), dict):
                continue
            if posixpath.basename(f) == "serverless.yml":
                continue  # handled by _serverless
            self._cfn_resources(doc["Resources"], f"cfn:{f}", f, f"cloudformation · {f}", posixpath.dirname(f) or ".")
            self.m.detectors.add("cloudformation")

    def _cfn_resources(self, resources, prefix, f, stack_label, base_dir, sid=None):
        sid = sid or self.stack(prefix, stack_label, platform="aws", file=f)
        ids = {}
        for logical, r in resources.items():
            if not isinstance(r, dict):
                continue
            rtype = str(r.get("Type", "resource"))
            props = r.get("Properties") or {}
            name = None
            if isinstance(props, dict):
                for k in ("FunctionName", "BucketName", "TableName", "QueueName", "TopicName", "DBInstanceIdentifier", "Name"):
                    if isinstance(props.get(k), str) and "!" not in props[k]:
                        name = props[k]
                        break
            ids[logical] = self.res(f"{prefix}/{logical}", logical, rtype, sid, platform="aws", file=f,
                                    meta={"cloud_name": name, "type": rtype})
        for logical, r in resources.items():
            if logical not in ids:
                continue
            blob = json.dumps(r.get("Properties") or {}) + json.dumps(r.get("DependsOn") or "")
            for other, oid in ids.items():
                if other != logical and re.search(rf"(?<![\w]){re.escape(other)}(?![\w])", blob):
                    self.m.edge(ids[logical], oid, "references")
            props = r.get("Properties") or {}
            if not isinstance(props, dict):
                continue
            code = props.get("CodeUri") or props.get("Code") or props.get("ContentUri")
            if isinstance(code, str):
                self.link_code(posixpath.join(base_dir, code), ids[logical])
            handler = props.get("Handler")
            if isinstance(handler, str) and not isinstance(code, str):
                self.link_code(posixpath.join(base_dir, posixpath.dirname(handler.replace(".", "/"))), ids[logical])
            for ev_name, ev in (props.get("Events") or {}).items() if isinstance(props.get("Events"), dict) else []:
                if not isinstance(ev, dict):
                    continue
                et = str(ev.get("Type", ""))
                eblob = json.dumps(ev.get("Properties") or {})
                linked = False
                for other, oid in ids.items():
                    if re.search(rf"(?<![\w]){re.escape(other)}(?![\w])", eblob):
                        self.m.edge(oid, ids[logical], "triggers", label=et)
                        linked = True
                if not linked and et in ("Api", "HttpApi"):
                    gw = self.res(f"{prefix}/ImplicitApi", "API Gateway (implicit)", "AWS::Serverless::Api", sid, platform="aws", file=f)
                    self.m.edge(gw, ids[logical], "routes_to", label=_short(json.dumps(ev.get("Properties", {}).get("Path", ""))))
                elif not linked and et in ("Schedule", "ScheduleV2"):
                    sch = self.res(f"{prefix}/{logical}-{ev_name}", ev_name, "AWS::Events::Rule", sid, platform="aws", file=f)
                    self.m.edge(sch, ids[logical], "triggers", label="schedule")
        return sid

    # -- Serverless Framework ---------------------------------------------
    def _serverless(self):
        for f in self.files:
            if posixpath.basename(f) not in ("serverless.yml", "serverless.yaml"):
                continue
            doc = yamlmini.load(self.m.read(f))
            if not isinstance(doc, dict):
                continue
            self.m.detectors.add("serverless")
            d = posixpath.dirname(f) or "."
            provider = doc.get("provider") or {}
            pname = provider.get("name", "aws") if isinstance(provider, dict) else "aws"
            sid = self.stack(f"sls:{f}", f"serverless · {doc.get('service', d)}", platform=pname, file=f)
            api = None
            for fname, fn in (doc.get("functions") or {}).items():
                if not isinstance(fn, dict):
                    continue
                fid = self.res(f"sls:{f}/{fname}", fname, f"{pname}_lambda_function", sid, platform=pname, file=f,
                               kind="function", meta={"handler": fn.get("handler")})
                h = fn.get("handler")
                if isinstance(h, str):
                    self.link_code(posixpath.join(d, posixpath.dirname(h)), fid)
                for ev in fn.get("events") or []:
                    if not isinstance(ev, dict):
                        continue
                    for et, ec in ev.items():
                        if et in ("http", "httpApi", "websocket", "alb"):
                            if api is None:
                                api = self.res(f"sls:{f}/api", "API Gateway", "AWS::ApiGateway", sid, platform=pname, file=f)
                            path = ec.get("path") if isinstance(ec, dict) else ec
                            self.m.edge(api, fid, "routes_to", label=_short(str(path)))
                        elif et in ("sqs", "sns", "s3", "stream", "kafka", "eventBridge", "schedule", "cloudwatchEvent"):
                            label = ec if isinstance(ec, str) else (ec.get("arn") or ec.get("bucket") or ec.get("topicName")
                                                                      or ec.get("rate") or et) if isinstance(ec, dict) else et
                            label = str(label)
                            src = self.res(f"sls:{f}/{et}:{_short(label, 40)}", f"{et}: {_short(label, 32)}",
                                           {"sqs": "aws_sqs_queue", "sns": "aws_sns_topic", "s3": "aws_s3_bucket",
                                            "stream": "aws_kinesis_stream", "kafka": "aws_msk_cluster"}.get(et, "aws_cloudwatch_event_rule"),
                                           sid, platform=pname, file=f)
                            self.m.edge(src, fid, "triggers")
            res = (doc.get("resources") or {}).get("Resources") if isinstance(doc.get("resources"), dict) else None
            if isinstance(res, dict):
                self._cfn_resources(res, f"sls:{f}", f, "", d, sid=sid)

    # -- CDK / Pulumi (regex heuristics) -----------------------------------
    def _cdk_pulumi(self):
        cdk_dirs = [posixpath.dirname(f) or "." for f in self.files if posixpath.basename(f) == "cdk.json"]
        pulumi_dirs = [posixpath.dirname(f) or "." for f in self.files if posixpath.basename(f) in ("Pulumi.yaml", "Pulumi.yml")]
        for kind, dirs in (("cdk", cdk_dirs), ("pulumi", pulumi_dirs)):
            for d in dirs:
                prefix = "" if d == "." else d + "/"
                srcs = [f for f in self.files if f.startswith(prefix) and f.endswith((".ts", ".js", ".py", ".go", ".cs"))
                        and "node_modules" not in f and "/test" not in f and ".d.ts" not in f]
                sid = self.stack(f"{kind}:{d}", f"{kind} · {d}", file=d)
                self.m.detectors.add(kind)
                for f in srcs:
                    self._iac_code_file(kind, d, f, sid)

    def _iac_code_file(self, kind, d, f, sid):
        text = self.m.read(f)
        var_ids = {}
        if kind == "cdk":
            rx = re.compile(r"(?:(?:const|let|var|this\.)\s*(\w+)\s*=\s*|(\w+)\s*=\s*)?new\s+([\w.]+)\(\s*(?:this|self|scope)\s*,\s*['\"]([^'\"]+)['\"]")
            rx_py = re.compile(r"(?:(\w+)\s*=\s*)?([\w.]+)\(\s*self\s*,\s*['\"]([^'\"]+)['\"]")
            matches = [(m.group(1) or m.group(2), m.group(3), m.group(4), m.start()) for m in rx.finditer(text)]
            if f.endswith(".py"):
                matches += [(m.group(1), m.group(2), m.group(3), m.start()) for m in rx_py.finditer(text)
                            if "." in m.group(2) and m.group(2)[0].islower()]
        else:
            rx = re.compile(r"(?:(?:const|let|var)\s+(\w+)\s*=\s*)?new\s+((?:aws|gcp|azure|azure_native|cloudflare|kubernetes|digitalocean|vercel)[\w.]*\.\w+)\(\s*['\"]([^'\"]+)['\"]")
            rx_py = re.compile(r"(?:(\w+)\s*=\s*)?((?:aws|gcp|azure|azure_native|cloudflare|kubernetes)\.[\w.]+)\(\s*['\"]([^'\"]+)['\"]")
            matches = [(m.group(1), m.group(2), m.group(3), m.start()) for m in (rx_py if f.endswith(".py") else rx).finditer(text)]
        for var, ctor, cid, pos in matches:
            if ctor.split(".")[-1] in ("App", "Stack", "Construct", "Stage") or ctor in ("cdk.App", "cdk.Stack"):
                continue
            rtype = ctor if kind == "pulumi" else f"aws.{ctor}"
            k = classify(ctor)
            if k == "resource" and kind == "cdk" and not re.search(r"^[a-z]\w*\.[A-Z]", ctor):
                continue  # custom construct class, not an AWS resource
            line = text.count("\n", 0, pos) + 1
            nid = self.res(f"{kind}:{d}/{cid}", cid, rtype, sid, platform=platform_of(rtype) or "aws", file=f"{f}:{line}")
            if var:
                var_ids[var] = nid
            # code asset for functions
            window = text[pos:pos + 800]
            for p in re.findall(r"(?:fromAsset|entry|codeUri|code_uri|from_asset|FileArchive|AssetArchive)\s*[:(=]\s*(?:path\.(?:join|resolve)\(\s*__dirname\s*,\s*)?['\"]([^'\"]+)['\"]", window):
                base = posixpath.dirname(f)
                self.link_code(posixpath.normpath(posixpath.join(base, p)), nid)
        for grantee_target in re.finditer(r"(\w+)\.grant(\w*)\(\s*(?:this\.)?(\w+)", text):
            res_var, how, who = grantee_target.groups()
            if res_var in var_ids and who in var_ids:
                self.m.edge(var_ids[who], var_ids[res_var], "accesses", label=how.lower() or "grant")
        for ev in re.finditer(r"(\w+)\.addEventSource\(\s*new\s+[\w.]+\(\s*(?:this\.)?(\w+)", text):
            fn, src = ev.groups()
            if fn in var_ids and src in var_ids:
                self.m.edge(var_ids[src], var_ids[fn], "triggers")
        for integ in re.finditer(r"new\s+[\w.]*(?:LambdaIntegration|HttpLambdaIntegration)\(\s*(?:['\"][^'\"]*['\"]\s*,\s*)?(?:this\.)?(\w+)", text):
            fn = integ.group(1)
            if fn in var_ids:
                apis = [v for v, n in var_ids.items() if self.m.nodes[n].get("kind") == "gateway"]
                for a in apis[:1]:
                    self.m.edge(var_ids[a], var_ids[fn], "routes_to")

    # -- Bicep -------------------------------------------------------------
    def _bicep(self):
        for f in self.files:
            if not f.endswith(".bicep"):
                continue
            text = self.m.read(f)
            sid = self.stack(f"bicep:{f}", f"bicep · {f}", platform="azure", file=f)
            self.m.detectors.add("bicep")
            syms = {}
            for mm in re.finditer(r"^\s*resource\s+(\w+)\s+'([\w.]+/[\w./]+)@[^']+'(\s+existing)?", text, re.M):
                sym, rtype = mm.group(1), mm.group(2)
                syms[sym] = self.res(f"bicep:{f}/{sym}", sym, rtype, sid, platform="azure", file=f"{f}:{text.count(chr(10), 0, mm.start()) + 1}")
            for mm in re.finditer(r"^\s*module\s+(\w+)\s+'([^']+)'", text, re.M):
                syms[mm.group(1)] = self.m.node(f"bicep:{f}/{mm.group(1)}", f"module {mm.group(1)}", layer="infra",
                                                kind="module", parent=sid, platform="azure", meta={"source": mm.group(2)})["id"]
            blocks = re.split(r"^\s*(?:resource|module)\s+", text, flags=re.M)
            for blk in blocks[1:]:
                sym = blk.split()[0]
                if sym not in syms:
                    continue
                for other, oid in syms.items():
                    if other != sym and re.search(rf"\b{other}\.(?:id|name|properties|outputs)", blk):
                        self.m.edge(syms[sym], oid, "references")

    # -- Kubernetes ----------------------------------------------------------
    def _kubernetes(self):
        workloads, services, ingresses = [], [], []
        for f in self.yaml_files(lambda f: "/.github/" not in "/" + f and not posixpath.basename(f).startswith(("docker-compose", "compose."))):
            text = self.m.read(f)
            if "apiVersion" not in text or "kind" not in text:
                continue
            if "{{" in text:  # helm template
                continue
            for doc in yamlmini.load_all(text):
                if not isinstance(doc, dict) or "kind" not in doc or "apiVersion" not in doc:
                    continue
                kind = str(doc["kind"])
                api = str(doc.get("apiVersion", ""))
                if kind == "List" or re.match(r"(skaffold|kustomize\.config\.k8s\.io|kpt|config\.kubernetes\.io)", api):
                    continue
                meta = doc.get("metadata") or {}
                name = str(meta.get("name", "?"))
                ns = str(meta.get("namespace", "default"))
                sid = self.stack(f"k8s:{ns}", f"k8s · ns {ns}", platform="kubernetes")
                nid = f"k8s:{ns}/{kind}/{name}"
                spec = doc.get("spec") or {}
                if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "ReplicaSet", "Pod", "Rollout"):
                    tmpl = spec.get("jobTemplate", {}).get("spec", {}).get("template") if kind == "CronJob" else spec.get("template")
                    pod = (tmpl or {}).get("spec") or (spec if kind == "Pod" else {})
                    labels = ((tmpl or {}).get("metadata") or {}).get("labels") or meta.get("labels") or {}
                    containers = (pod.get("containers") or []) + (pod.get("initContainers") or [])
                    images = [c.get("image") for c in containers if isinstance(c, dict)]
                    image = next((i for i in images if i), "")
                    k, _ = image_kind(image)
                    self.m.node(nid, name, layer="infra", kind=k if k != "compute" else "compute", tech=f"k8s {kind}",
                                parent=sid, platform="kubernetes", file=f,
                                meta={"images": images, "replicas": spec.get("replicas"), "schedule": spec.get("schedule")})
                    workloads.append((nid, ns, labels, pod, containers))
                    for img in images:
                        self.link_image(img, nid)
                elif kind == "Service":
                    self.m.node(nid, name, layer="infra", kind="gateway" if spec.get("type") == "LoadBalancer" else "service",
                                tech="k8s Service", parent=sid, platform="kubernetes", file=f,
                                meta={"type": spec.get("type"), "ports": [p.get("port") for p in spec.get("ports") or [] if isinstance(p, dict)]},
                                low_level=True)
                    services.append((nid, ns, name, spec.get("selector") or {}))
                elif kind in ("Ingress", "HTTPRoute", "IngressRoute", "Gateway", "VirtualService"):
                    self.m.node(nid, name, layer="infra", kind="gateway", tech=f"k8s {kind}", parent=sid,
                                platform="kubernetes", file=f,
                                meta={"hosts": [r.get("host") for r in spec.get("rules") or [] if isinstance(r, dict) and r.get("host")]})
                    ingresses.append((nid, ns, doc))
                elif kind in ("ConfigMap", "Secret", "SealedSecret", "ExternalSecret"):
                    self.m.node(nid, name, layer="infra", kind="secret", tech=f"k8s {kind}", parent=sid,
                                platform="kubernetes", file=f, low_level=True)
                elif kind in ("PersistentVolumeClaim",):
                    self.m.node(nid, name, layer="infra", kind="bucket", tech="k8s PVC", parent=sid, platform="kubernetes", file=f, low_level=True)
                elif kind in ("HorizontalPodAutoscaler", "NetworkPolicy", "ServiceAccount", "Role", "RoleBinding",
                              "ClusterRole", "ClusterRoleBinding", "PodDisruptionBudget", "Namespace"):
                    continue
                else:
                    self.m.node(nid, name, layer="infra", kind=classify(kind), tech=f"k8s {kind}", parent=sid,
                                platform="kubernetes", file=f)
                self.m.detectors.add("kubernetes")
        for sid_, ns, name, selector in services:
            for wid, wns, labels, pod, _ in workloads:
                if wns == ns and selector and all(labels.get(k) == v for k, v in selector.items()):
                    self.m.edge(sid_, wid, "routes_to")
        svc_by_name = {(ns, name): sid_ for sid_, ns, name, _ in services}
        for iid, ns, doc in ingresses:
            blob = json.dumps(doc.get("spec") or {})
            for nm in set(re.findall(r'"(?:serviceName|name|host)":\s*"([^"]+)"', blob)):
                nm = nm.split(".")[0]
                if (ns, nm) in svc_by_name:
                    self.m.edge(iid, svc_by_name[(ns, nm)], "routes_to")
        for wid, ns, labels, pod, containers in workloads:
            blob = json.dumps(pod)
            for nm in set(re.findall(r'"(?:name|secretName|claimName)":\s*"([^"]+)"', blob)):
                for k in ("ConfigMap", "Secret", "PersistentVolumeClaim", "SealedSecret", "ExternalSecret"):
                    if f"k8s:{ns}/{k}/{nm}" in self.m.nodes:
                        self.m.edge(wid, f"k8s:{ns}/{k}/{nm}", "uses")
            # service DNS names in env values
            env_blob = re.sub(r'"image":\s*"[^"]*"', "", blob)
            for (sns, sname), sid_ in svc_by_name.items():
                if (sid_, wid, "routes_to") in self.m.edges:
                    continue  # the workload's own service
                if re.search(rf"(?:://|@|=|\"){re.escape(sname)}(?:\.{re.escape(sns)})?(?:\.svc[\w.]*)?:\d+", env_blob):
                    self.m.edge(wid, sid_, "calls")
        # Helm charts
        for f in self.files:
            if posixpath.basename(f) == "Chart.yaml":
                doc = yamlmini.load(self.m.read(f)) or {}
                d = posixpath.dirname(f)
                sid = self.stack(f"helm:{d}", f"helm · {doc.get('name', d)}", platform="kubernetes", file=f)
                values = yamlmini.load(self.m.read(f"{d}/values.yaml")) or {}
                images = set(re.findall(r'"repository":\s*"([^"]+)"', json.dumps(values)))
                nid = self.m.node(f"helm:{d}/release", doc.get("name", d), layer="infra", kind="compute",
                                  tech="helm chart", parent=sid, platform="kubernetes", file=f,
                                  meta={"images": sorted(images), "dependencies": [x.get("name") for x in doc.get("dependencies") or [] if isinstance(x, dict)]})["id"]
                for img in images:
                    self.link_image(img, nid)
                for dep in doc.get("dependencies") or []:
                    if isinstance(dep, dict) and dep.get("name"):
                        k, ext = image_kind(dep["name"])
                        did = self.m.node(f"helm:{d}/dep/{dep['name']}", dep["name"], layer="infra", kind=k,
                                          tech="helm dependency", parent=sid, platform="kubernetes")["id"]
                        self.m.edge(nid, did, "uses")
                self.m.detectors.add("helm")

    # -- Docker Compose -------------------------------------------------------
    def _compose(self):
        for f in self.files:
            base = posixpath.basename(f)
            if not re.match(r"^(docker-)?compose([.\-][\w.-]+)?\.ya?ml$", base):
                continue
            doc = yamlmini.load(self.m.read(f))
            if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
                continue
            self.m.detectors.add("compose")
            d = posixpath.dirname(f) or "."
            sid = self.stack(f"compose:{f}", f"compose · {f}", platform="docker", file=f)
            ids = {}
            for name, svc in doc["services"].items():
                svc = svc if isinstance(svc, dict) else {}
                image = svc.get("image") or ""
                build = svc.get("build")
                if build:
                    k = "compute"
                    ext = None
                else:
                    k, ext = image_kind(image)
                ids[name] = self.m.node(f"compose:{f}/{name}", name, layer="infra", kind=k,
                                        tech=f"container {image}".strip() if image else "container (built)",
                                        parent=sid, platform="docker", file=f,
                                        meta={"image": image, "ports": svc.get("ports"), "build": build if isinstance(build, str) else (build or {}).get("context") if isinstance(build, dict) else None,
                                              "profiles": svc.get("profiles")})["id"]
                if build:
                    ctx = build if isinstance(build, str) else (build.get("context") or ".") if isinstance(build, dict) else "."
                    self.link_code(posixpath.normpath(posixpath.join(d, ctx)), ids[name])
                elif image:
                    self.link_image(image, ids[name])
            for name, svc in doc["services"].items():
                if not isinstance(svc, dict):
                    continue
                deps = svc.get("depends_on") or []
                deps = list(deps.keys()) if isinstance(deps, dict) else deps
                for dep in deps + (svc.get("links") or []):
                    dep = str(dep).split(":")[0]
                    if dep in ids:
                        self.m.edge(ids[name], ids[dep], "depends_on")
                env = json.dumps(svc.get("environment") or {}) + json.dumps(svc.get("command") or "")
                for other, oid in ids.items():
                    if other != name and re.search(rf"(?:://|@|=|\"){re.escape(other)}(?::\d+|/|\"|$)", env):
                        self.m.edge(ids[name], oid, "connects")

    # -- Cloudflare -------------------------------------------------------------
    def _wrangler(self):
        for f in self.files:
            base = posixpath.basename(f)
            if base not in ("wrangler.toml", "wrangler.json", "wrangler.jsonc"):
                continue
            text = self.m.read(f)
            cfg = load_toml(text) if base.endswith(".toml") else load_json(text, jsonc=True)
            if not isinstance(cfg, dict):
                continue
            self.m.detectors.add("cloudflare")
            d = posixpath.dirname(f) or "."
            name = cfg.get("name") or d
            sid = self.stack("cloudflare", "Cloudflare", platform="cloudflare")
            kind = "function"
            if cfg.get("pages_build_output_dir") or cfg.get("site") or cfg.get("assets"):
                kind = "function" if cfg.get("main") else "hosting"
            wid = self.m.node(f"cf:worker:{name}", name, layer="infra", kind=kind, tech="Cloudflare Worker" if kind == "function" else "Cloudflare Pages",
                              parent=sid, platform="cloudflare", file=f,
                              meta={"routes": cfg.get("routes") or cfg.get("route"), "compat_date": cfg.get("compatibility_date"),
                                    "crons": (cfg.get("triggers") or {}).get("crons")})["id"]
            main = cfg.get("main")
            if main:
                self.link_code(posixpath.normpath(posixpath.join(d, main)), wid) or self.link_code(d, wid)
            else:
                self.link_code(d, wid)
            envs = [cfg] + [e for e in (cfg.get("env") or {}).values() if isinstance(e, dict)]
            for c in envs:
                self._cf_bindings(c, wid, sid, f)
            crons = (cfg.get("triggers") or {}).get("crons")
            if crons:
                cid = self.m.node(f"cf:cron:{name}", "Cron Trigger", layer="infra", kind="queue", tech="Cloudflare Cron",
                                  parent=sid, platform="cloudflare", meta={"crons": crons})["id"]
                self.m.edge(cid, wid, "triggers", label=", ".join(map(str, crons))[:40])

    def _cf_bindings(self, c, wid, sid, f):
        def add(kind_key, label_key, rtype, k, ident_key="binding", edge="uses"):
            for b in c.get(kind_key) or []:
                if not isinstance(b, dict):
                    continue
                label = b.get(label_key) or b.get(ident_key) or "?"
                nid = self.m.node(f"cf:{rtype}:{label}", label, layer="infra", kind=k, tech=f"Cloudflare {rtype}",
                                  parent=sid, platform="cloudflare", file=f, meta={"binding": b.get(ident_key)})["id"]
                self.m.edge(wid, nid, edge, label=b.get(ident_key))
        add("kv_namespaces", "binding", "KV", "cache")
        add("d1_databases", "database_name", "D1", "database")
        add("r2_buckets", "bucket_name", "R2", "bucket")
        add("vectorize", "index_name", "Vectorize", "database")
        add("hyperdrive", "binding", "Hyperdrive", "database")
        add("analytics_engine_datasets", "dataset", "Analytics Engine", "observability")
        add("services", "service", "Worker", "function", edge="calls")
        do = c.get("durable_objects") or {}
        for b in do.get("bindings") or [] if isinstance(do, dict) else []:
            if isinstance(b, dict):
                nid = self.m.node(f"cf:DO:{b.get('class_name')}", b.get("class_name") or b.get("name"), layer="infra", kind="database",
                                  tech="Durable Object", parent=sid, platform="cloudflare", file=f)["id"]
                self.m.edge(wid, nid, "uses", label=b.get("name"))
        q = c.get("queues") or {}
        if isinstance(q, dict):
            for b in q.get("producers") or []:
                if isinstance(b, dict):
                    nid = self.m.node(f"cf:Queue:{b.get('queue')}", b.get("queue"), layer="infra", kind="queue",
                                      tech="Cloudflare Queue", parent=sid, platform="cloudflare", file=f)["id"]
                    self.m.edge(wid, nid, "publishes")
            for b in q.get("consumers") or []:
                if isinstance(b, dict):
                    nid = self.m.node(f"cf:Queue:{b.get('queue')}", b.get("queue"), layer="infra", kind="queue",
                                      tech="Cloudflare Queue", parent=sid, platform="cloudflare", file=f)["id"]
                    self.m.edge(nid, wid, "triggers")
        if c.get("ai"):
            nid = self.m.node("cf:AI", "Workers AI", layer="infra", kind="service", tech="Workers AI", parent=sid, platform="cloudflare")["id"]
            self.m.edge(wid, nid, "uses")

    # -- PaaS: Vercel, Netlify, Fly, Railway, Render, Heroku, App Runner -----------
    def _paas(self):
        for f in self.files:
            base = posixpath.basename(f)
            d = posixpath.dirname(f) or "."
            text = None
            if base == "vercel.json":
                cfg = load_json(self.m.read(f), jsonc=True) or {}
                sid = self.stack("vercel", "Vercel", platform="vercel")
                pid = self.m.node(f"vercel:{d}", f"vercel · {posixpath.basename(d) if d != '.' else self.m.nodes.get('pkg:.', {}).get('label', 'app')}",
                                  layer="infra", kind="hosting", tech="Vercel project", parent=sid, platform="vercel", file=f,
                                  meta={"crons": cfg.get("crons"), "regions": cfg.get("regions")})["id"]
                self.link_code(d, pid)
                if cfg.get("crons"):
                    cid = self.m.node(f"vercel:{d}/crons", "Vercel Cron", layer="infra", kind="queue", tech="Vercel Cron",
                                      parent=sid, platform="vercel", meta={"crons": cfg["crons"]})["id"]
                    self.m.edge(cid, pid, "triggers")
                self.m.detectors.add("vercel")
            elif base == "netlify.toml":
                cfg = load_toml(self.m.read(f)) or {}
                sid = self.stack("netlify", "Netlify", platform="netlify")
                pid = self.m.node(f"netlify:{d}", f"netlify · {posixpath.basename(d) if d != '.' else 'site'}", layer="infra",
                                  kind="hosting", tech="Netlify site", parent=sid, platform="netlify", file=f,
                                  meta={"build": cfg.get("build")})["id"]
                self.link_code(d, pid)
                fdir = ((cfg.get("functions") or {}).get("directory") if isinstance(cfg.get("functions"), dict) else None) or \
                       ((cfg.get("build") or {}).get("functions") if isinstance(cfg.get("build"), dict) else None)
                if fdir:
                    fid = self.m.node(f"netlify:{d}/functions", "Netlify Functions", layer="infra", kind="function",
                                      tech="Netlify Functions", parent=sid, platform="netlify")["id"]
                    self.link_code(posixpath.join(d, fdir), fid)
                    self.m.edge(pid, fid, "routes_to")
                self.m.detectors.add("netlify")
            elif base == "fly.toml":
                cfg = load_toml(self.m.read(f)) or {}
                sid = self.stack("fly", "Fly.io", platform="fly")
                pid = self.m.node(f"fly:{cfg.get('app', d)}", cfg.get("app", d), layer="infra", kind="compute", tech="Fly app",
                                  parent=sid, platform="fly", file=f,
                                  meta={"region": cfg.get("primary_region"), "mounts": cfg.get("mounts")})["id"]
                self.link_code(d, pid)
                self.m.detectors.add("fly")
            elif base in ("railway.json", "railway.toml"):
                sid = self.stack("railway", "Railway", platform="railway")
                pid = self.m.node(f"railway:{d}", f"railway · {posixpath.basename(d) if d != '.' else 'service'}", layer="infra",
                                  kind="compute", tech="Railway service", parent=sid, platform="railway", file=f)["id"]
                self.link_code(d, pid)
                self.m.detectors.add("railway")
            elif base == "render.yaml":
                cfg = yamlmini.load(self.m.read(f)) or {}
                sid = self.stack("render", "Render", platform="render")
                ids = {}
                for db in cfg.get("databases") or []:
                    if isinstance(db, dict):
                        ids[db.get("name")] = self.m.node(f"render:db:{db.get('name')}", db.get("name"), layer="infra",
                                                          kind="database", tech="Render Postgres", parent=sid, platform="render", file=f)["id"]
                for s in cfg.get("services") or []:
                    if not isinstance(s, dict):
                        continue
                    t = s.get("type", "web")
                    k = {"web": "compute", "worker": "compute", "cron": "queue", "redis": "cache", "keyvalue": "cache",
                         "pserv": "compute", "static": "hosting"}.get(t, "compute")
                    ids[s.get("name")] = self.m.node(f"render:{s.get('name')}", s.get("name"), layer="infra", kind=k,
                                                     tech=f"Render {t}", parent=sid, platform="render", file=f)["id"]
                    self.link_code(posixpath.join(d, s.get("rootDir") or "."), ids[s.get("name")])
                for s in cfg.get("services") or []:
                    if not isinstance(s, dict):
                        continue
                    blob = json.dumps(s.get("envVars") or [])
                    for nm in re.findall(r'"name":\s*"([^"]+)"', blob):
                        if nm in ids and nm != s.get("name"):
                            self.m.edge(ids[s.get("name")], ids[nm], "uses")
                self.m.detectors.add("render")
            elif base == "Procfile":
                text = self.m.read(f)
                sid = self.stack("heroku", "Heroku", platform="heroku")
                for proc, cmd in re.findall(r"^(\w+):\s*(.+)$", text, re.M):
                    pid = self.m.node(f"heroku:{d}/{proc}", f"{proc} dyno", layer="infra", kind="compute", tech="Heroku dyno",
                                      parent=sid, platform="heroku", file=f, meta={"cmd": cmd[:120]})["id"]
                    self.link_code(d, pid)
                self.m.detectors.add("heroku")
            elif base == "app.json" and '"addons"' in (text := self.m.read(f)):
                cfg = load_json(text) or {}
                sid = self.stack("heroku", "Heroku", platform="heroku")
                for a in cfg.get("addons") or []:
                    plan = a if isinstance(a, str) else a.get("plan", "")
                    k, _ = image_kind(plan)
                    self.m.node(f"heroku:addon:{plan}", plan, layer="infra", kind=k, tech="Heroku add-on", parent=sid, platform="heroku")
            elif base == "apprunner.yaml":
                sid = self.stack("aws-apprunner", "AWS App Runner", platform="aws")
                pid = self.m.node(f"apprunner:{d}", f"app runner · {d}", layer="infra", kind="compute", tech="App Runner",
                                  parent=sid, platform="aws", file=f)["id"]
                self.link_code(d, pid)
            elif base in ("app.yaml",) and "runtime:" in self.m.read(f):
                sid = self.stack("gcp-appengine", "App Engine", platform="gcp")
                pid = self.m.node(f"appengine:{d}", f"app engine · {d}", layer="infra", kind="compute", tech="App Engine",
                                  parent=sid, platform="gcp", file=f)["id"]
                self.link_code(d, pid)
        # Next.js app without explicit hosting config: hint only, no node.
        for pid, n in list(self.m.nodes.items()):
            if pid.startswith("pkg:") and "Next.js" in (n.get("meta") or {}).get("frameworks", []):
                if not any(e["source"] == pid and e["kind"] == "deploys_to" for e in self.m.edges.values()):
                    n.setdefault("meta", {})["hosting_hint"] = "Next.js app with no hosting config found (often Vercel)"

    def _firebase(self):
        for f in self.files:
            if posixpath.basename(f) != "firebase.json":
                continue
            cfg = load_json(self.m.read(f), jsonc=True) or {}
            d = posixpath.dirname(f) or "."
            sid = self.stack("firebase", "Firebase", platform="firebase")
            self.m.detectors.add("firebase")
            hosting = cfg.get("hosting")
            for h in (hosting if isinstance(hosting, list) else [hosting] if hosting else []):
                if isinstance(h, dict):
                    hid = self.m.node(f"firebase:hosting:{h.get('target') or h.get('site') or 'default'}", f"Hosting {h.get('target') or ''}".strip(),
                                      layer="infra", kind="hosting", tech="Firebase Hosting", parent=sid, platform="firebase", file=f)["id"]
                    self.link_code(posixpath.join(d, posixpath.dirname(h.get("public", ".")) or "."), hid)
            funcs = cfg.get("functions")
            for fn in (funcs if isinstance(funcs, list) else [funcs] if funcs else []):
                if isinstance(fn, dict):
                    fid = self.m.node(f"firebase:functions:{fn.get('codebase', 'default')}", f"Functions ({fn.get('codebase', 'default')})",
                                      layer="infra", kind="function", tech="Cloud Functions for Firebase", parent=sid, platform="firebase", file=f)["id"]
                    self.link_code(posixpath.join(d, fn.get("source", "functions")), fid)
            for key, k, label in (("firestore", "database", "Firestore"), ("database", "database", "Realtime Database"),
                                  ("storage", "bucket", "Cloud Storage")):
                if cfg.get(key):
                    self.m.node(f"firebase:{key}", label, layer="infra", kind=k, tech=f"Firebase {label}", parent=sid, platform="firebase", file=f)

    def _supabase(self):
        cfgs = [f for f in self.files if f.endswith("supabase/config.toml")]
        for f in cfgs:
            d = posixpath.dirname(f)
            cfg = load_toml(self.m.read(f)) or {}
            sid = self.stack("supabase", f"Supabase · {cfg.get('project_id', '')}".strip(" ·"), platform="supabase")
            self.m.detectors.add("supabase")
            db = self.m.node("supabase:db", "Postgres", layer="infra", kind="database", tech="Supabase Postgres", parent=sid,
                             platform="supabase", file=f)["id"]
            tables = set()
            for mf in self.files:
                if mf.startswith(d + "/migrations/") and mf.endswith(".sql"):
                    tables.update(re.findall(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:\"?public\"?\.)?\"?(\w+)", self.m.read(mf), re.I))
            if tables:
                self.m.node(db, meta={"tables": sorted(tables)[:200]})
            fn_names = sorted({mf.split("/")[mf.split("/").index("functions") + 1] for mf in self.files
                               if mf.startswith(d + "/functions/") and len(mf.split("/")) > len(d.split("/")) + 2})
            for fn in fn_names:
                if fn.startswith("_"):
                    continue
                fid = self.m.node(f"supabase:fn:{fn}", fn, layer="infra", kind="function", tech="Supabase Edge Function",
                                  parent=sid, platform="supabase")["id"]
                self.link_code(f"{d}/functions/{fn}", fid)
                self.m.edge(fid, db, "uses")
            if (cfg.get("storage") or {}).get("enabled", False):
                self.m.node("supabase:storage", "Storage", layer="infra", kind="bucket", tech="Supabase Storage", parent=sid, platform="supabase")
            if (cfg.get("auth") or {}).get("enabled", True) and cfg.get("auth") is not None:
                self.m.node("supabase:auth", "Auth", layer="infra", kind="auth", tech="Supabase Auth", parent=sid, platform="supabase")
            if "ext:supabase" in self.m.nodes:
                self.m.node("ext:supabase", meta={"note": "managed by supabase/ (see Supabase stack)"})
                self.m.edge("ext:supabase", db, "same_as")

    def _prisma(self):
        for f in self.files:
            if not f.endswith(".prisma"):
                continue
            text = self.m.read(f)
            prov = re.search(r'datasource\s+\w+\s*\{[^}]*provider\s*=\s*"(\w+)"', text, re.S)
            if not prov:
                continue
            provider = prov.group(1)
            ext_id = {"postgresql": "postgres", "postgres": "postgres", "mysql": "mysql", "mongodb": "mongodb",
                      "sqlite": "sqlite", "sqlserver": "sqlserver", "cockroachdb": "postgres"}.get(provider, provider)
            models = re.findall(r"^\s*model\s+(\w+)\s*\{", text, re.M)
            node = ext_node(self.m, ext_id, f"prisma datasource in {f}")
            node.setdefault("meta", {})["models"] = models[:200]
            pkg = self.code.package_of(f)
            if pkg is not None and f"pkg:{pkg}" in self.m.nodes:
                self.m.edge(f"pkg:{pkg}", node["id"], "uses", label="prisma")
            self.m.detectors.add("prisma")
        for f in self.files:
            if re.search(r"(^|/)drizzle\.config\.(ts|js|mjs)$", f):
                text = self.m.read(f)
                dialect = re.search(r"(?:dialect|driver)\s*:\s*['\"](\w+)", text)
                if dialect:
                    ext_id = {"postgresql": "postgres", "pg": "postgres", "mysql": "mysql", "sqlite": "sqlite",
                              "turso": "turso", "d1-http": "d1"}.get(dialect.group(1), dialect.group(1))
                    node = ext_node(self.m, ext_id, f"drizzle config {f}")
                    pkg = self.code.package_of(f)
                    if pkg is not None and f"pkg:{pkg}" in self.m.nodes:
                        self.m.edge(f"pkg:{pkg}", node["id"], "uses", label="drizzle")
                    self.m.detectors.add("drizzle")

    # -- CI/CD ---------------------------------------------------------------------
    CI_TARGETS = [
        (r"cloudflare/wrangler-action|wrangler\s+(?:deploy|publish|pages\s+deploy)", "cloudflare"),
        (r"amondnet/vercel-action|vercel\s+(?:deploy|--prod)|vercel-action", "vercel"),
        (r"netlify\s+deploy|nwtgck/actions-netlify|netlify/actions", "netlify"),
        (r"flyctl\s+deploy|superfly/flyctl-actions", "fly"),
        (r"railway\s+up|railwayapp/", "railway"),
        (r"terraform\s+apply|hashicorp/setup-terraform|tofu\s+apply|terraform-github-actions", "terraform"),
        (r"aws-actions/amazon-ecs-deploy|ecs\s+update-service|aws-actions/aws-cloudformation|sam\s+deploy|cdk\s+deploy|"
         r"serverless\s+deploy|sls\s+deploy|aws\s+s3\s+sync|aws\s+lambda\s+update|aws-actions/configure-aws-credentials", "aws"),
        (r"google-github-actions/deploy-cloudrun|gcloud\s+run\s+deploy|google-github-actions/deploy-appengine|gcloud\s+functions\s+deploy|google-github-actions/auth", "gcp"),
        (r"azure/webapps-deploy|azure/functions-action|az\s+(?:webapp|containerapp|deployment)|azure/login", "azure"),
        (r"kubectl\s+apply|helm\s+(?:upgrade|install)|azure/k8s-deploy|argocd", "kubernetes"),
        (r"firebase\s+deploy|FirebaseExtended/action-hosting-deploy", "firebase"),
        (r"supabase\s+(?:db\s+push|functions\s+deploy|link)", "supabase"),
        (r"docker/build-push-action|docker\s+push", "registry"),
        (r"heroku\s+|akhileshns/heroku-deploy", "heroku"),
        (r"render\.com/deploy|render-deploy", "render"),
        (r"expo\s+publish|eas\s+(?:build|submit|update)", "expo"),
        (r"npm\s+publish|pnpm\s+publish|changesets/action", "npm"),
    ]

    def _ci(self):
        wf_files = [f for f in self.files if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", f)]
        other = [f for f in self.files if f in (".gitlab-ci.yml", "bitbucket-pipelines.yml", "azure-pipelines.yml",
                                                 ".circleci/config.yml", "cloudbuild.yaml", "buildspec.yml", "Jenkinsfile")]
        if not wf_files and not other:
            return
        self.m.detectors.add("ci")
        sid = self.m.node("stack:ci", "CI / CD", layer="ci", kind="stack")["id"]
        for f in wf_files + other:
            text = self.m.read(f)
            doc = yamlmini.load(text) if f.endswith((".yml", ".yaml")) else None
            name = (doc.get("name") if isinstance(doc, dict) else None) or posixpath.basename(f)
            triggers = None
            if isinstance(doc, dict):
                on = doc.get("on", doc.get(True))
                triggers = list(on.keys()) if isinstance(on, dict) else on if isinstance(on, list) else [on] if on else None
            cid = self.m.node(f"ci:{f}", str(name), layer="ci", kind="workflow", parent=sid, file=f,
                              tech="GitHub Actions" if f.startswith(".github") else posixpath.basename(f),
                              meta={"triggers": triggers})["id"]
            wdirs = set(re.findall(r"working-directory:\s*['\"]?([\w./-]+)", text))
            for rx, target in self.CI_TARGETS:
                if not re.search(rx, text):
                    continue
                for t in self._ci_target_nodes(target, wdirs):
                    self.m.edge(cid, t, "deploys")

    def _ci_target_nodes(self, target, wdirs):
        stacks = [n for n in self.m.nodes.values() if n["id"].startswith("stack:") and n.get("layer") == "infra"]
        if target == "terraform":
            tf = [s["id"] for s in stacks if s["id"].startswith("stack:tf:")]
            chosen = [s for s in tf if any(s.endswith(":" + w.strip("./")) or s.endswith(":" + w) for w in wdirs)]
            return chosen or tf[:3]
        if target == "aws":
            return [s["id"] for s in stacks if s["id"].startswith(("stack:cfn:", "stack:sls:", "stack:cdk:"))] or \
                [self._platform_node("aws")]
        if target == "kubernetes":
            return [s["id"] for s in stacks if s["id"].startswith(("stack:k8s:", "stack:helm:"))] or [self._platform_node("kubernetes")]
        direct = f"stack:{target}"
        if direct in self.m.nodes:
            return [direct]
        if target in ("npm", "expo"):
            return [self._platform_node(target, kind="registry")]
        return [self._platform_node(target)]

    def _platform_node(self, p, kind="platform"):
        return self.m.node(f"plat:{p}", PLATFORM_LABELS.get(p, p), layer="infra", kind=kind, platform=p)["id"]


# --------------------------------------------------------------------------
# HCL helpers
# --------------------------------------------------------------------------

def _hcl_body(text, start):
    """Return the text of a {...} block starting at text[start] == '{'."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                i += 1
        elif c == "#" or text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            e = text.find("*/", i)
            i = n if e == -1 else e + 1
        elif text.startswith("<<", i):
            mm = re.match(r"<<-?\s*(\w+)", text[i:])
            if mm:
                e = re.search(rf"^\s*{mm.group(1)}\s*$", text[i + mm.end():], re.M)
                i = n if not e else i + mm.end() + e.end()
                continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    return text[start + 1:]


def _hcl_literal(body, attrs, raw=False):
    for a in attrs:
        mm = re.search(rf'^\s*{a}\s*=\s*(.+)$', body, re.M)
        if mm:
            v = mm.group(1).strip()
            if raw:
                return v
            sm = re.match(r'^"([^"$]*)"', v)
            if sm:
                return sm.group(1)
    return None


def _short(s, n=28):
    s = str(s).strip('"')
    return s if len(s) <= n else s[: n - 1] + "…"
