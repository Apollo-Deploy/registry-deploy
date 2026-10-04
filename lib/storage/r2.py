#!/usr/bin/env python3
"""R2 access remains on the registry host; clients receive only registry credentials."""

import json
from pathlib import Path

import boto3
from botocore.config import Config

CONFIG_DIR = Path("/etc/apollo-registry")


def settings():
    return json.loads((CONFIG_DIR / "settings.json").read_text())


def r2_client():
    values = settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{values['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=values["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4",
            connect_timeout=15,
            read_timeout=120,
            retries={"max_attempts": 3},
            s3={"addressing_style": "path"},
        ),
    )
