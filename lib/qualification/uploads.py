#!/usr/bin/env python3
"""Exercise accepted multipart uploads, interrupted requests, restart resume, and cleanup."""

import http.client
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from lib.verification.oci import digest, require


def report(check, **measurements):
    print(json.dumps({"check": check, "result": "PASS", **measurements}), flush=True)


def upload_prefix(repository, location):
    match = re.search(r"/uploads/([a-f0-9-]+)", location)
    require(match is not None, "upload-uuid")
    upload_id = match.group(1)
    return f"registry/docker/registry/v2/repositories/{repository}/_uploads/{upload_id}/"


def restart_registry(registry):
    subprocess.run(
        ["systemctl", "restart", "apollo-registry.service"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            if registry.request("GET", "/v2/")[0] == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(2)
    raise RuntimeError("restart-health")


def interrupted_upload(registry, repository, s3, bucket):
    # Drop a TCP connection midway through a PATCH body, then discover committed bytes.
    chunk_size = 16 * 1024 * 1024
    payload = os.urandom(2 * chunk_size)
    location = registry.start_upload(repository)
    status, headers, _ = registry.request(
        "PATCH",
        location,
        payload[:chunk_size],
        "application/octet-stream",
        headers={"Content-Range": f"0-{chunk_size - 1}"},
    )
    require(status == 202, "accepted-first-chunk")
    location = headers["Location"]
    prefix = upload_prefix(repository, location)
    pending = s3.list_multipart_uploads(Bucket=bucket, Prefix=prefix).get("Uploads", [])
    require(len(pending) == 1, "distribution-multipart-session")
    parts = s3.list_parts(Bucket=bucket, Key=pending[0]["Key"], UploadId=pending[0]["UploadId"])
    require(len(parts.get("Parts", [])) >= 2, "distribution-multipart-parts")
    report("distribution-r2-multipart", accepted_parts=len(parts["Parts"]))
    restart_registry(registry)
    status, headers, _ = registry.request("GET", location)
    require(
        status == 204 and headers.get("Range") == f"0-{chunk_size - 1}",
        "accepted-chunk-restart-resume",
    )
    location = headers["Location"]
    report("accepted-multipart-restart-resume", committed_bytes=chunk_size)
    target = urlsplit(location)
    require(target.scheme == "https" and target.netloc == registry.host, "origin")
    path = target.path + "?" + target.query
    connection = http.client.HTTPSConnection(registry.host, timeout=30, context=registry.context)
    connection.putrequest("PATCH", path)
    connection.putheader("Authorization", registry.authorization)
    connection.putheader("Content-Type", "application/octet-stream")
    connection.putheader("Content-Length", str(chunk_size))
    connection.putheader("Content-Range", f"{chunk_size}-{len(payload) - 1}")
    connection.endheaders()
    connection.send(payload[chunk_size : chunk_size + 10 * 1024 * 1024])
    connection.close()
    time.sleep(3)
    restart_registry(registry)
    status, headers, _ = registry.request("GET", location)
    if status != 204:
        # A dropped response can leave R2 ahead of the last signed Location offset.
        # OCI clients must retry from a fresh session when that state cannot resume.
        require(status in (400, 404, 416), "interrupted-upload-status")
        identity = registry.push_blob(repository, payload)
        status, _, body = registry.request("GET", f"/v2/{repository}/blobs/{identity}")
        require(status == 200 and digest(body) == identity, "fresh-retry-digest")
        report("interrupted-upload-retry", recovery="fresh-session-after-stale-offset")
        return
    location = headers["Location"]
    bounds = headers.get("Range", "0-0")
    end = int(bounds.split("-")[-1])
    # Distribution uses 0-0 for an empty upload (there is no committed byte).
    offset = end + 1 if end > 0 else 0
    require(chunk_size <= offset < len(payload), "resume-offset")
    status, headers, _ = registry.request(
        "PATCH",
        location,
        payload[offset:],
        "application/octet-stream",
        headers={"Content-Range": f"{offset}-{len(payload)-1}"},
    )
    require(status == 202, "resume-patch")
    location = headers["Location"]
    status, _, _ = registry.request(
        "PUT", location + "&digest=" + digest(payload), b"", "application/octet-stream"
    )
    require(status == 201, "resume-commit")
    status, _, body = registry.request("GET", f"/v2/{repository}/blobs/{digest(payload)}")
    require(status == 200 and digest(body) == digest(payload), "resume-digest")
    require(
        not s3.list_multipart_uploads(Bucket=bucket, Prefix=prefix).get("Uploads"),
        "multipart-commit-cleanup",
    )
    report("interrupted-upload-retry-resume-restart", committed_before_retry=offset)


def cleanup_uploads(registry, repository, s3, bucket):
    location = registry.start_upload(repository)
    prefix = upload_prefix(repository, location)
    status, _, _ = registry.request("DELETE", location)
    require(status == 204, "upload-cancel")
    require(
        not s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents"),
        "upload-cancel-cleanup",
    )
    require(
        not s3.list_multipart_uploads(Bucket=bucket, Prefix=prefix).get("Uploads"),
        "cancel-multipart-cleanup",
    )
    report("cancel-upload-cleanup")

    # Age only our new probe's metadata, to exercise the real scheduled purger.
    location = registry.start_upload(repository)
    prefix = upload_prefix(repository, location)
    started_at = datetime.now(timezone.utc) - timedelta(days=3)
    s3.put_object(
        Bucket=bucket,
        Key=prefix + "startedat",
        Body=started_at.strftime("%Y-%m-%dT%H:%M:%SZ").encode(),
    )
    deadline = time.monotonic() + 7500
    while time.monotonic() < deadline:
        if not s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents"):
            report("scheduled-upload-purge")
            # Exercise the production orphan cleaner, restricted to our exact UUID prefix.
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lib.runtime.upload_cleanup",
                    "--older-than-hours",
                    "0",
                    "--prefix",
                    prefix,
                ],
                check=True,
            )
            require(
                not s3.list_multipart_uploads(Bucket=bucket, Prefix=prefix).get("Uploads"),
                "orphan-multipart-cleanup",
            )
            report("orphan-multipart-cleanup")
            return
        print(json.dumps({"check": "scheduled-upload-purge", "result": "WAIT"}), flush=True)
        time.sleep(30)
    raise RuntimeError("scheduled-upload-purge-timeout")
