#!/usr/bin/env python3
"""Forward signals and sanitize Distribution logs before any bytes reach journald."""

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import yaml


def redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    # Remove complete URL queries, including escaped JSON quotes, and auth values.
    text = re.sub(r'(https?://[^\s?"\\]+)\?[^\s"\\]*', r"\1?[REDACTED]", text)
    text = re.sub(r"(\b(?:Basic|Bearer)\s+)[A-Za-z0-9+/=._-]+", r"\1[REDACTED]", text)
    return text


def sanitize(value, secrets):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            lower = key.lower()
            if any(
                word in lower
                for word in ("authorization", "password", "secret", "accesskey", "header")
            ):
                clean[key] = "[REDACTED]"
            elif "uri" in lower or "url" in lower:
                clean[key] = redact(str(item).split("?", 1)[0], secrets)
            else:
                clean[key] = sanitize(item, secrets)
        return clean
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        return redact(value, secrets)
    return value


def main():
    credentials = Path(os.environ["CREDENTIALS_DIRECTORY"])
    config = yaml.safe_load((credentials / "config.yml").read_text())
    client = json.loads((credentials / "client.json").read_text())
    s3 = config["storage"]["s3"]
    secrets = [s3["accesskey"], s3["secretkey"], config["http"]["secret"], client["password"]]
    process = subprocess.Popen(
        ["/opt/apollo-registry/current", "serve", str(credentials / "config.yml")],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def forward(signum, _frame):
        if process.poll() is None:
            process.send_signal(signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    for line in process.stdout:
        try:
            value = json.loads(line)
            print(json.dumps(sanitize(value, secrets)), flush=True)
        except ValueError:
            # Startup errors may embed YAML, so unstructured output is never logged.
            print('{"level":"error","msg":"unstructured registry log suppressed"}', flush=True)
    return process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print('{"level":"error","msg":"registry supervisor failed"}', flush=True)
        sys.exit(1)
