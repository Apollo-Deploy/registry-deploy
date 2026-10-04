#!/usr/bin/env python3
"""Abort aged, incomplete registry upload sessions. Never delete completed objects."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from lib.storage.r2 import r2_client, settings

ROOT = "registry/docker/registry/v2/repositories/"
UPLOAD_KEY = re.compile(re.escape(ROOT) + r"[a-z0-9_./-]+/_uploads/[a-f0-9-]{36}/data$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-hours", type=float, default=25)
    parser.add_argument("--prefix", default=ROOT)
    arguments = parser.parse_args()
    if arguments.older_than_hours < 0:
        raise ValueError("Cleanup age cannot be negative.")
    # A short age is an operator-directed action and must target one exact upload UUID.
    if arguments.prefix == ROOT and arguments.older_than_hours < 25:
        raise ValueError("Global cleanup requires an age of at least 25 hours.")
    if arguments.prefix != ROOT and not UPLOAD_KEY.fullmatch(arguments.prefix + "data"):
        raise ValueError("Cleanup prefix must identify one registry upload.")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=arguments.older_than_hours)
    s3 = r2_client()
    bucket = settings()["R2_BUCKET"]
    aborted = 0
    paginator = s3.get_paginator("list_multipart_uploads")
    for page in paginator.paginate(Bucket=bucket, Prefix=arguments.prefix):
        for upload in page.get("Uploads", []):
            if not UPLOAD_KEY.fullmatch(upload["Key"]) or upload["Initiated"] >= cutoff:
                continue
            s3.abort_multipart_upload(Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"])
            aborted += 1
    print(json.dumps({"check": "orphan-upload-cleanup", "result": "PASS", "aborted": aborted}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"check":"orphan-upload-cleanup","result":"FAIL"}', file=sys.stderr)
        sys.exit(1)
