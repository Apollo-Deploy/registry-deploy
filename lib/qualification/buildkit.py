#!/usr/bin/env python3
"""Prove remote cache import after a dedicated worker's local cache is emptied."""

import base64
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from lib.verification.oci import ProbeFailure, Registry, require


def command(arguments, environment):
    # BuildKit output may contain signed URLs. Inspect it in memory, never log it.
    result = subprocess.run(
        arguments, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    require(result.returncode == 0, "buildkit-command")
    return result.stdout


def main():
    directory = Path(sys.argv[1]) / "buildkit"
    directory.mkdir(mode=0o700)
    registry = Registry()
    client = registry.client
    # Pass only client/runtime settings: server-side R2/AWS environment secrets
    # must never reach buildctl or its frontend session.
    allowed_environment = (
        "PATH",
        "HOME",
        "XDG_RUNTIME_DIR",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "BUILDKIT_HOST",
    )
    environment = {key: os.environ[key] for key in allowed_environment if key in os.environ}
    credentials = directory / "credentials"
    credentials.mkdir(mode=0o700)
    context = directory / "context"
    context.mkdir(mode=0o700)
    environment["DOCKER_CONFIG"] = str(credentials)
    auth = base64.b64encode((client["username"] + ":" + client["password"]).encode()).decode()
    (credentials / "config.json").write_text(
        json.dumps({"auths": {client["hostname"]: {"auth": auth}}})
    )
    (credentials / "config.json").chmod(0o600)
    nonce = uuid.uuid4().hex
    base = os.environ["BUILDKIT_BASE_IMAGE"]
    (context / "Dockerfile").write_text(
        f'FROM {base}\nRUN printf "{nonce}\\n" > /cache-qualification\n'
    )
    repository = "qualification/build-cache-" + nonce
    ref = client["hostname"] + "/" + repository + ":cache"
    buildctl = ["buildctl", "--addr", environment["BUILDKIT_HOST"]]
    build = buildctl + [
        "build",
        "--progress=plain",
        "--frontend",
        "dockerfile.v0",
        "--local",
        f"context={context}",
        "--local",
        f"dockerfile={context}",
    ]
    first = command(build + ["--export-cache", f"type=registry,ref={ref},mode=max"], environment)
    require("exporting cache to registry" in first, "cache-export")
    status, _, _ = registry.request(
        "GET",
        f"/v2/{repository}/manifests/cache",
        headers={
            "Accept": "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.oci.image.index.v1+json"
        },
    )
    require(status == 200, "remote-cache-manifest")
    command(buildctl + ["prune", "--all"], environment)
    usage = command(
        buildctl + ["du", "--format", "{{.ID}}"],
        environment,
    )
    require(not usage.strip(), "worker-cache-not-empty")
    second = command(build + ["--import-cache", f"type=registry,ref={ref}"], environment)
    step = re.search(r"(#\d+) \[[^\]]+\] RUN printf", second)
    require(
        step is not None and re.search(re.escape(step.group(1)) + r" CACHED\b", second),
        "remote-run-cache-hit",
    )
    print(
        json.dumps(
            {
                "check": "buildkit-export-prune-import-run-cache-hit",
                "result": "PASS",
                "ref": ref,
                "local_cache_empty_before_import": True,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        check = error.check if isinstance(error, ProbeFailure) else "buildkit-cache"
        print(
            json.dumps(
                {
                    "check": check,
                    "result": "FAIL",
                    "detail": "BuildKit output suppressed to protect credential material.",
                }
            ),
            flush=True,
        )
        sys.exit(1)
