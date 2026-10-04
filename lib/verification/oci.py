#!/usr/bin/env python3
"""Small OCI protocol probe. Passwords stay in files/memory; TLS and origin checks are mandatory."""

import base64
import hashlib
import http.client
import json
import ssl
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_DIR = Path("/etc/apollo-registry")

MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"


class ProbeFailure(RuntimeError):
    def __init__(self, check):
        self.check = check
        super().__init__(check)


def require(condition, check):
    if not condition:
        raise ProbeFailure(check)


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Registry:
    def __init__(self, timeout=300):
        self.timeout = timeout
        self.client = json.loads((CONFIG_DIR / "client.json").read_text())
        self.host = self.client["hostname"]
        raw = (self.client["username"] + ":" + self.client["password"]).encode()
        self.authorization = "Basic " + base64.b64encode(raw).decode()
        self.context = ssl.create_default_context()
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def request(self, method, path, data=None, content_type=None, authenticated=True, headers=None):
        target = urlsplit(path)
        # Never follow redirects or send credentials to an arbitrary Location origin.
        require(
            not target.netloc or (target.scheme == "https" and target.netloc == self.host), "origin"
        )
        path = target.path + ("?" + target.query if target.query else "")
        outgoing = dict(headers or {})
        if authenticated:
            outgoing["Authorization"] = self.authorization
        if content_type:
            outgoing["Content-Type"] = content_type
        connection = http.client.HTTPSConnection(
            self.host, timeout=self.timeout, context=self.context
        )
        try:
            connection.request(method, path, body=data, headers=outgoing)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def start_upload(self, repository):
        status, headers, _ = self.request("POST", f"/v2/{repository}/blobs/uploads/", b"")
        require(status == 202 and "Location" in headers, "upload-start")
        return headers["Location"]

    def push_blob(self, repository, data):
        identity = digest(data)
        status, _, _ = self.request("HEAD", f"/v2/{repository}/blobs/{identity}")
        if status == 200:
            return identity
        require(status == 404, "blob-head")
        location = self.start_upload(repository)
        separator = "&" if "?" in location else "?"
        status, _, _ = self.request(
            "PUT", location + separator + "digest=" + identity, data, "application/octet-stream"
        )
        require(status == 201, "blob-push")
        return identity

    def push_artifact(self, repository, tag, payload):
        config = b"{}"
        config_digest = self.push_blob(repository, config)
        payload_digest = self.push_blob(repository, payload)
        manifest = {
            "schemaVersion": 2,
            "mediaType": MEDIA_TYPE,
            "artifactType": "application/vnd.registry.qualification",
            "config": {
                "mediaType": "application/vnd.oci.empty.v1+json",
                "digest": config_digest,
                "size": len(config),
            },
            "layers": [
                {
                    "mediaType": "application/octet-stream",
                    "digest": payload_digest,
                    "size": len(payload),
                }
            ],
        }
        encoded = json.dumps(manifest, separators=(",", ":")).encode()
        identity = digest(encoded)
        status, _, _ = self.request("PUT", f"/v2/{repository}/manifests/{tag}", encoded, MEDIA_TYPE)
        require(status == 201, "manifest-push")
        return identity, payload_digest

    def pull_artifact(self, repository, identity, payload_digest):
        status, _, body = self.request(
            "GET", f"/v2/{repository}/manifests/{identity}", headers={"Accept": MEDIA_TYPE}
        )
        require(status == 200 and digest(body) == identity, "manifest-digest")
        manifest = json.loads(body)
        require(manifest["layers"][0]["digest"] == payload_digest, "layer-reference")
        status, _, body = self.request("GET", f"/v2/{repository}/blobs/{payload_digest}")
        require(status == 200 and digest(body) == payload_digest, "payload-digest")
        return len(body)
