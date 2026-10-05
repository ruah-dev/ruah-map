#!/usr/bin/env python3
"""Regression test: scan + render the fixture monorepo and assert key facts.

Run: python3 tests/test_fixture.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")


def main():
    out = tempfile.mkdtemp(prefix="ruah-test-")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "scan.py"), os.path.join(HERE, "fixture"), "--out", out],
                   check=True, capture_output=True)
    d = json.load(open(os.path.join(out, "model.json")))
    ids = {n["id"] for n in d["nodes"]}
    edges = {(e["source"], e["kind"], e["target"]) for e in d["edges"]}
    tf = "tf:infra/terraform/"

    expect_nodes = ["pkg:apps/web", "pkg:apps/api", "pkg:packages/ui", "pkg:services/worker", "ext:stripe",
                    "ext:postgres", f"{tf}aws_lambda_function.worker", "k8s:acme/Deployment/api",
                    "compose:docker-compose.yml/db", "cf:worker:acme-router", "cf:R2:acme-assets",
                    "vercel:apps/web", "ci:.github/workflows/deploy.yml"]
    expect_edges = [
        ("mod:apps/web/src/app", "imports", "mod:apps/web/src/lib"),            # tsconfig alias @/
        ("mod:apps/web/src/app", "imports", "pkg:packages/ui"),                 # workspace package
        ("mod:apps/web/src/lib", "uses", "ext:stripe"),                         # SDK import
        ("mod:apps/api/app/routes", "imports", "mod:apps/api/app/services"),    # python relative import
        ("pkg:services/worker", "deploys_to", f"{tf}aws_lambda_function.worker"),  # archive_file source_dir
        (f"{tf}aws_sqs_queue.orders", "triggers", f"{tf}aws_lambda_function.worker"),  # event source mapping
        (f"{tf}aws_lambda_function.worker", "accesses", f"{tf}aws_s3_bucket.uploads"),  # IAM bridge
        ("pkg:apps/api", "deploys_to", "k8s:acme/Deployment/api"),              # image name -> Dockerfile dir
        ("k8s:acme/Ingress/public", "routes_to", "k8s:acme/Service/api"),
        ("k8s:acme/Deployment/api", "calls", "k8s:acme/Service/redis"),
        ("compose:docker-compose.yml/web", "connects", "compose:docker-compose.yml/api"),
        ("mod:edge/router/src", "deploys_to", "cf:worker:acme-router"),
        ("ci:.github/workflows/deploy.yml", "deploys", "stack:tf:infra/terraform"),
        ("pkg:apps/web", "uses", "ext:postgres"),                               # prisma datasource
    ]
    unexpected_edges = [("k8s:acme/Deployment/api", "calls", "k8s:acme/Service/api")]

    failures = [f"missing node {n}" for n in expect_nodes if n not in ids]
    failures += [f"missing edge {e}" for e in expect_edges if e not in edges]
    failures += [f"unexpected edge {e}" for e in unexpected_edges if e in edges]
    if "pkg:." in ids:
        failures.append("empty workspace root should be dropped")
    if d["warnings"]:
        failures.append(f"scanner warnings: {d['warnings']}")

    # render with a minimal enrichment, check validation catches bad ids
    with open(os.path.join(out, "enrich.json"), "w") as f:
        json.dump({"summary": "x", "flows": [{"name": "f", "steps": ["pkg:apps/web", "nope"]}]}, f)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "render.py"), out, "--validate"], capture_output=True, text=True)
    if r.returncode == 0 or "nope" not in r.stdout:
        failures.append("validate should flag unknown id 'nope'")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "render.py"), out, "--md", os.path.join(out, "A.md")],
                   check=True, capture_output=True)
    html = open(os.path.join(out, "architecture.html")).read()
    if "__MODEL__" in html or "pkg:apps/web" not in html:
        failures.append("html not rendered with model")
    if "```mermaid" not in open(os.path.join(out, "A.md")).read():
        failures.append("markdown missing mermaid block")

    if failures:
        print("FAIL\n  " + "\n  ".join(failures))
        sys.exit(1)
    print(f"OK — {len(ids)} nodes, {len(edges)} edges, {len(expect_edges)} edge assertions")


if __name__ == "__main__":
    main()
