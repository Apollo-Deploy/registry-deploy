#!/usr/bin/env python3
"""Verify HTTPS, OCI authentication, and durable R2 storage from the registry host."""

import http.client
import json
import sys

from lib.storage.r2 import r2_client, settings
from lib.verification.oci import ProbeFailure, Registry, require


def verify_blob_in_r2(payload_digest):
    value = payload_digest.split(":")[1]
    key = f"registry/docker/registry/v2/blobs/sha256/{value[:2]}/{value}/data"
    response = r2_client().head_object(Bucket=settings()["R2_BUCKET"], Key=key)
    require(response["ContentLength"] > 0, "r2-blob")


def smoke():
    registry = Registry(timeout=15)
    status, headers, _ = registry.request("GET", "/v2/", authenticated=False)
    require(status == 401 and "WWW-Authenticate" in headers, "anonymous-access")
    status, headers, _ = registry.request("GET", "/v2/")
    require(
        status == 200 and headers.get("Docker-Distribution-Api-Version") == "registry/2.0", "v2"
    )
    repository = "qualification/health"
    identity, payload_digest = registry.push_artifact(repository, "probe", b"registry health v1\n")
    registry.pull_artifact(repository, identity, payload_digest)
    verify_blob_in_r2(payload_digest)
    # Debug listener is loopback-only, and never needs auth or credentials.
    connection = http.client.HTTPConnection("127.0.0.1", 5001, timeout=10)
    try:
        connection.request("GET", "/debug/health")
        response = connection.getresponse()
        require(response.status == 200 and json.loads(response.read()) == {}, "storage-health")
    finally:
        connection.close()


def main():
    if sys.argv[1] == "r2-check":
        r2_client().list_objects_v2(Bucket=settings()["R2_BUCKET"], MaxKeys=1)
    else:
        smoke()
    print(
        json.dumps(
            {"health": "PASS", "tls": "VALID", "authentication": "ENABLED", "r2": "CONNECTED"}
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        check = error.check if isinstance(error, ProbeFailure) else "https-auth-oci-r2"
        print(json.dumps({"health": "FAIL", "check": check}))
        sys.exit(1)
