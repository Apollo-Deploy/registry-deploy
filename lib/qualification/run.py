#!/usr/bin/env python3
"""Qualify real Distribution/R2 behavior, using only uniquely owned test uploads/keys."""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lib.qualification.uploads import (
    cleanup_uploads,
    interrupted_upload,
    restart_registry,
)
from lib.storage.r2 import r2_client, settings
from lib.verification.health import verify_blob_in_r2
from lib.verification.oci import ProbeFailure, Registry, digest, require


def report(check, **measurements):
    print(json.dumps({"check": check, "result": "PASS", **measurements}), flush=True)


def service_snapshot():
    process = subprocess.run(
        ["systemctl", "show", "apollo-registry.service", "-p", "ControlGroup"],
        check=True,
        capture_output=True,
        text=True,
    )
    group = Path("/sys/fs/cgroup") / process.stdout.strip().split("=", 1)[1].lstrip("/")
    cpu = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
    rss_kib = 0
    for pid in (group / "cgroup.procs").read_text().split():
        try:
            status = Path("/proc", pid, "status").read_text()
        except FileNotFoundError:
            continue
        match = re.search(r"^VmRSS:\s+(\d+)", status, re.MULTILINE)
        if match:
            rss_kib += int(match.group(1))
    return {
        "rss_bytes": rss_kib * 1024,
        "cgroup_memory_bytes": int((group / "memory.current").read_text()),
        "cpu_usec": int(cpu["usage_usec"]),
    }


def multipart(s3, bucket, namespace):
    key = "qualification-s3/" + namespace + "/multipart"
    upload_id = None
    try:
        response = s3.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = response["UploadId"]
        parts = []
        payload = os.urandom(6 * 1024 * 1024)
        for number in (1, 2):
            response = s3.upload_part(
                Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=payload
            )
            parts.append({"PartNumber": number, "ETag": response["ETag"]})
        s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
        )
        upload_id = None
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        require(digest(body) == digest(payload * 2), "multipart-digest")
        s3.delete_object(Bucket=bucket, Key=key)
        require(not s3.list_objects_v2(Bucket=bucket, Prefix=key).get("Contents"), "s3-delete")
        response = s3.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = response["UploadId"]
        s3.upload_part(Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=1, Body=payload)
        s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        upload_id = None
        uploads = s3.list_multipart_uploads(Bucket=bucket, Prefix=key).get("Uploads", [])
        require(not uploads, "multipart-abort")
        report("r2-multipart-delete-abort")
    finally:
        # Cleanup never enumerates/deletes registry objects or another run's prefix.
        if upload_id is not None:
            s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        s3.delete_object(Bucket=bucket, Key=key)


def main():
    namespace = uuid.uuid4().hex
    repository = "qualification/" + namespace
    registry = Registry()
    s3 = r2_client()
    bucket = settings()["R2_BUCKET"]
    for method, path in [
        ("POST", f"/v2/{repository}/blobs/uploads/"),
        ("PUT", f"/v2/{repository}/manifests/anonymous"),
        ("DELETE", f"/v2/{repository}/manifests/sha256:" + "0" * 64),
    ]:
        require(
            registry.request(method, path, b"", authenticated=False)[0] == 401, "anonymous-write"
        )
    report("anonymous-push-delete-denied")
    require(registry.request("GET", "/v2/")[0] == 200, "authenticated-v2")
    identity, blob = registry.push_artifact(repository, "small", os.urandom(4096))
    registry.pull_artifact(repository, identity, blob)
    verify_blob_in_r2(blob)
    require(
        registry.request("DELETE", f"/v2/{repository}/manifests/{identity}")[0] == 405,
        "authenticated-delete-disabled",
    )
    report("small-oci-push-pull-digest-r2-delete-disabled")
    restart_registry(registry)
    registry.pull_artifact(repository, identity, blob)
    report("restart-persistence")
    interrupted_upload(registry, repository, s3, bucket)
    before = service_snapshot()
    peak_rss_bytes = before["rss_bytes"]
    sampling_done = threading.Event()

    def sample():
        nonlocal peak_rss_bytes

        while not sampling_done.wait(1):
            current_rss_bytes = service_snapshot()["rss_bytes"]
            peak_rss_bytes = max(peak_rss_bytes, current_rss_bytes)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    workload_started = time.monotonic()
    size = int(os.environ.get("QUALIFY_LARGE_MIB", "128")) * 1024 * 1024
    require(64 * 1024 * 1024 <= size <= 1024 * 1024 * 1024, "large-size")
    started = time.monotonic()
    identity, blob = registry.push_artifact(repository, "large", os.urandom(size))
    push_seconds = time.monotonic() - started
    started = time.monotonic()
    registry.pull_artifact(repository, identity, blob)
    pull_seconds = time.monotonic() - started
    verify_blob_in_r2(blob)
    report(
        "large-oci",
        bytes=size,
        push_mib_sec=size / push_seconds / 1048576,
        pull_mib_sec=size / pull_seconds / 1048576,
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: Registry().pull_artifact(repository, identity, blob), range(4))
        )
    require(results == [size] * 4, "concurrent-pull")
    report("concurrent-pulls", workers=4)

    def push(index):
        local = Registry()
        manifest, layer = local.push_artifact(
            repository, "parallel-" + str(index), os.urandom(8 * 1048576)
        )
        local.pull_artifact(repository, manifest, layer)
        verify_blob_in_r2(layer)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(push, range(4)))
    report("concurrent-pushes", workers=4)
    multipart(s3, bucket, namespace)
    sampling_done.set()
    sampler.join()
    after = service_snapshot()
    elapsed = time.monotonic() - workload_started
    disk = subprocess.run(
        ["du", "-sb", "/etc/apollo-registry", "/var/lib/apollo-registry", "/opt/apollo-registry"],
        capture_output=True,
        text=True,
        check=True,
    )
    report(
        "resource-sample",
        rss_peak_bytes=peak_rss_bytes,
        rss_end_bytes=after["rss_bytes"],
        service_cpu_seconds=(after["cpu_usec"] - before["cpu_usec"]) / 1000000,
        service_mean_cpu_cores=(after["cpu_usec"] - before["cpu_usec"]) / elapsed / 1000000,
        local_disk_bytes=sum(int(line.split()[0]) for line in disk.stdout.splitlines()),
        sample_note="one-second process RSS samples; no hard resource cap asserted",
    )
    cleanup_uploads(registry, repository, s3, bucket)
    report(
        "distribution-r2-suite",
        repository=repository,
        retained="OCI probe artifacts retained; delete disabled by production policy",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        check = error.check if isinstance(error, ProbeFailure) else "distribution-r2-qualification"
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "check": check,
                    "detail": "Exception content suppressed to protect credentials.",
                }
            ),
            flush=True,
        )
        sys.exit(1)
