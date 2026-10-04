"""Render private server configuration while preserving its upload-signing secret."""

import json
import os
import secrets
from pathlib import Path

import yaml

from lib.configuration.validation import validate


def private_write(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def render(settings, destination, template):
    validate(settings)
    settings.setdefault("HTTP_SECRET", secrets.token_hex(32))
    config = yaml.safe_load(Path(template).read_text())
    s3 = config["storage"]["s3"]
    s3.update(
        accesskey=settings["R2_ACCESS_KEY_ID"],
        secretkey=settings["R2_SECRET_ACCESS_KEY"],
        bucket=settings["R2_BUCKET"],
        regionendpoint=f"https://{settings['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    )
    config["http"].update(
        host="https://" + settings["REGISTRY_HOSTNAME"], secret=settings["HTTP_SECRET"]
    )
    client = {
        "hostname": settings["REGISTRY_HOSTNAME"],
        "username": settings["REGISTRY_USERNAME"],
        "password": settings["REGISTRY_PASSWORD"],
    }
    directory = Path(destination)
    private_write(directory / "settings.json", json.dumps(settings))
    private_write(directory / "client.json", json.dumps(client))
    private_write(directory / "config.yml", yaml.safe_dump(config, sort_keys=False))
