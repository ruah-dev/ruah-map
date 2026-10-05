"""Optional live cloud discovery. Read-only list/describe calls only.

Every command here is a list/describe/get call. Nothing mutates cloud state.
Results are merged into the model and matched against IaC-declared resources
to show drift (declared-but-not-found / live-but-not-in-code).
"""
import json
import re
import shutil
import subprocess

from .infra import LOW_LEVEL, PLATFORM_LABELS

AWS_SERVICE_KIND = {
    "lambda": "function", "s3": "bucket", "dynamodb": "database", "rds": "database", "sqs": "queue", "sns": "queue",
    "events": "queue", "states": "queue", "scheduler": "queue", "kinesis": "queue", "ecs": "compute", "eks": "compute",
    "ec2": "network", "apigateway": "gateway", "execute-api": "gateway", "cloudfront": "gateway",
    "elasticloadbalancing": "gateway", "elasticache": "cache", "iam": "iam", "logs": "observability",
    "cloudwatch": "observability", "secretsmanager": "secret", "kms": "secret", "ssm": "secret", "ecr": "container",
    "cognito-idp": "auth", "route53": "dns", "acm": "dns", "apprunner": "compute", "amplify": "hosting",
    "es": "database", "aoss": "database", "bedrock": "service",
}


def _run(cmd, timeout=45):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip().splitlines()[-1:] or ["failed"]
    try:
        return json.loads(r.stdout or "null"), None
    except json.JSONDecodeError:
        return r.stdout.strip(), None


def discover(model, providers, aws_region=None, gcp_project=None):
    report = {}
    for p in providers:
        fn = {"aws": _aws, "gcp": _gcp, "azure": _azure, "k8s": _k8s, "kubernetes": _k8s}.get(p)
        if fn is None:
            report[p] = "unknown provider"
            continue
        try:
            report[p] = fn(model, aws_region if p == "aws" else gcp_project if p == "gcp" else None)
        except Exception as e:  # never fail the scan
            report[p] = f"error: {e}"
    model.live_report = report
    return report


def _add_live(model, platform, scope, items):
    """items: list of dicts {name, kind, type, id}. Matches against IaC nodes."""
    plat = {"k8s": "kubernetes"}.get(platform, platform)
    sid = model.node(f"stack:live:{platform}:{scope}", f"live · {PLATFORM_LABELS.get(plat, plat)} · {scope}",
                     layer="infra", kind="stack", platform=plat, status="live")["id"]
    iac = [n for n in model.nodes.values() if n.get("layer") == "infra" and n.get("platform") == plat
           and not n["id"].startswith(("stack:", "plat:"))]
    index = {}
    for n in iac:
        for key in {str((n.get("meta") or {}).get("cloud_name") or ""), str(n.get("label") or "")}:
            if key:
                index.setdefault(key.lower(), []).append(n)
    matched = set()
    added = 0
    for it in items:
        name = str(it.get("name") or "")
        hits = [n for n in index.get(name.lower(), []) if n.get("kind") == it.get("kind") or it.get("kind") is None]
        if hits:
            for n in hits:
                n["status"] = "deployed"
                n.setdefault("meta", {})["live_id"] = it.get("id")
                matched.add(n["id"])
            continue
        model.node(f"live:{platform}:{it.get('type')}:{name}", name, layer="infra", kind=it.get("kind") or "resource",
                   tech=it.get("type"), parent=sid, platform=plat, status="live_only",
                   low_level=(it.get("kind") in LOW_LEVEL) or None, meta={"live_id": it.get("id"), "scope": scope})
        added += 1
    missing = 0
    for n in iac:
        if n["id"] in matched or n.get("kind") in LOW_LEVEL:
            continue
        if (n.get("meta") or {}).get("cloud_name"):
            n["status"] = "not_found_live"
            missing += 1
    model.detectors.add(f"live:{platform}")
    return {"items": len(items), "matched_iac": len(matched), "live_only": added, "declared_not_found": missing}


# ---------------------------------------------------------------- AWS
def _aws(model, region):
    if not shutil.which("aws"):
        return "aws CLI not installed"
    reg = ["--region", region] if region else []
    ident, err = _run(["aws", "sts", "get-caller-identity", "--output", "json"])
    if err:
        return f"not authenticated: {err}"
    account = ident.get("Account", "?")
    region = region or (_run(["aws", "configure", "get", "region"])[0] or "default")
    arns = set()
    tagged, _ = _run(["aws", "resourcegroupstaggingapi", "get-resources", "--output", "json", *reg], timeout=90)
    for r in (tagged or {}).get("ResourceTagMappingList", []) if isinstance(tagged, dict) else []:
        arns.add(r["ResourceARN"])
    calls = [
        (["aws", "lambda", "list-functions"], lambda j: [f["FunctionArn"] for f in j.get("Functions", [])]),
        (["aws", "dynamodb", "list-tables"], lambda j: [f"arn:aws:dynamodb:{region}:{account}:table/{t}" for t in j.get("TableNames", [])]),
        (["aws", "sqs", "list-queues"], lambda j: [f"arn:aws:sqs:{region}:{account}:{u.rsplit('/', 1)[-1]}" for u in j.get("QueueUrls", [])]),
        (["aws", "sns", "list-topics"], lambda j: [t["TopicArn"] for t in j.get("Topics", [])]),
        (["aws", "rds", "describe-db-instances"], lambda j: [d["DBInstanceArn"] for d in j.get("DBInstances", [])]),
        (["aws", "ecs", "list-clusters"], lambda j: j.get("clusterArns", [])),
        (["aws", "apigatewayv2", "get-apis"], lambda j: [f"arn:aws:apigateway:{region}::/apis/{a['Name']}" for a in j.get("Items", [])]),
        (["aws", "apigateway", "get-rest-apis"], lambda j: [f"arn:aws:apigateway:{region}::/restapis/{a['name']}" for a in j.get("items", [])]),
        (["aws", "elasticache", "describe-cache-clusters"], lambda j: [c["ARN"] for c in j.get("CacheClusters", []) if "ARN" in c]),
    ]
    for cmd, extract in calls:
        j, e = _run(cmd + ["--output", "json"] + reg)
        if isinstance(j, dict):
            try:
                arns.update(extract(j))
            except Exception:
                pass
    j, _ = _run(["aws", "s3api", "list-buckets", "--output", "json"])
    for b in (j or {}).get("Buckets", []) if isinstance(j, dict) else []:
        arns.add(f"arn:aws:s3:::{b['Name']}")
    items = []
    for arn in sorted(arns):
        parts = arn.split(":", 5)
        if len(parts) < 6:
            continue
        svc, rest = parts[2], parts[5]
        rtype, _, name = rest.partition("/") if "/" in rest else rest.partition(":")
        if not name:
            name, rtype = rtype, svc
        if svc == "ec2" and rtype == "instance":
            kind = "compute"
        else:
            kind = AWS_SERVICE_KIND.get(svc, "resource")
        if svc == "lambda":
            name = name.split(":")[0]
        items.append({"name": name.split("/")[-1] if svc != "apigateway" else name.split("/")[-1],
                      "kind": kind, "type": f"aws:{svc}:{rtype}", "id": arn})
    return _add_live(model, "aws", f"{account}/{region}", items)


# ---------------------------------------------------------------- GCP
def _gcp(model, project):
    if not shutil.which("gcloud"):
        return "gcloud CLI not installed"
    project = project or (_run(["gcloud", "config", "get-value", "project"])[0] or "")
    project = project.strip() if isinstance(project, str) else ""
    if not project:
        return "no gcloud project configured"
    items = []
    j, err = _run(["gcloud", "asset", "search-all-resources", f"--scope=projects/{project}", "--format=json", "--page-size=500"], timeout=120)
    if isinstance(j, list):
        for r in j:
            at = r.get("assetType", "")
            svc = at.split(".")[0]
            kind = ("function" if "Function" in at else "compute" if re.search(r"run\.|Instance$|Cluster$", at) else
                    "bucket" if "Bucket" in at else "database" if re.search(r"sqladmin|firestore|spanner|bigtable|bigquery", at) else
                    "queue" if "pubsub" in at or "cloudtasks" in at or "scheduler" in at else
                    "iam" if "iam" in at else "network" if "compute.googleapis.com" in at else "resource")
            items.append({"name": r.get("displayName") or r.get("name", "").rsplit("/", 1)[-1], "kind": kind, "type": at, "id": r.get("name")})
    else:
        for cmd, kind, t in (
            (["gcloud", "run", "services", "list"], "compute", "run.Service"),
            (["gcloud", "functions", "list"], "function", "cloudfunctions.Function"),
            (["gcloud", "sql", "instances", "list"], "database", "sqladmin.Instance"),
            (["gcloud", "storage", "buckets", "list"], "bucket", "storage.Bucket"),
            (["gcloud", "pubsub", "topics", "list"], "queue", "pubsub.Topic"),
        ):
            j, _ = _run(cmd + [f"--project={project}", "--format=json"])
            for r in j or [] if isinstance(j, list) else []:
                nm = r.get("metadata", {}).get("name") or r.get("name", "")
                items.append({"name": nm.rsplit("/", 1)[-1], "kind": kind, "type": t, "id": nm})
    return _add_live(model, "gcp", project, items)


# ---------------------------------------------------------------- Azure
def _azure(model, _):
    if not shutil.which("az"):
        return "az CLI not installed"
    acct, err = _run(["az", "account", "show", "-o", "json"])
    if err:
        return f"not authenticated: {err}"
    j, err = _run(["az", "resource", "list", "-o", "json"], timeout=120)
    items = []
    for r in j or [] if isinstance(j, list) else []:
        t = r.get("type", "")
        from .infra import classify
        items.append({"name": r.get("name"), "kind": classify(t), "type": t, "id": r.get("id")})
    return _add_live(model, "azure", acct.get("name", "subscription") if isinstance(acct, dict) else "subscription", items)


# ---------------------------------------------------------------- Kubernetes
def _k8s(model, _):
    if not shutil.which("kubectl"):
        return "kubectl not installed"
    ctx, err = _run(["kubectl", "config", "current-context"])
    if err:
        return f"no context: {err}"
    j, err = _run(["kubectl", "get", "deploy,statefulset,daemonset,cronjob,ingress", "-A", "-o", "json"], timeout=60)
    items = []
    for it in (j or {}).get("items", []) if isinstance(j, dict) else []:
        k = it.get("kind")
        md = it.get("metadata", {})
        if md.get("namespace", "").startswith("kube-"):
            continue
        items.append({"name": md.get("name"), "kind": "gateway" if k == "Ingress" else "compute",
                      "type": f"k8s {k}", "id": f"{md.get('namespace')}/{k}/{md.get('name')}"})
    return _add_live(model, "k8s", str(ctx).strip(), items)
