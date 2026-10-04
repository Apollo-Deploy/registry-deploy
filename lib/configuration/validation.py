"""Validate settings without changing the host or executing input values."""

import ipaddress
import re
from pathlib import Path

FIELDS = {
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "REGISTRY_HOSTNAME",
    "REGISTRY_USERNAME",
    "REGISTRY_PASSWORD",
    "TLS_CERTIFICATE",
    "TLS_KEY",
    "MANAGEMENT_CIDR",
    "SSH_PORT",
}


def require(condition):
    if not condition:
        raise ValueError("invalid settings")


def validate(settings):
    validate_fields(settings)
    validate_storage(settings)
    validate_hostname(settings["REGISTRY_HOSTNAME"])
    validate_credentials(settings)
    validate_tls_paths(settings)
    validate_management_access(settings)


def validate_fields(settings):
    require(FIELDS <= settings.keys())
    require(not (settings.keys() - FIELDS - {"HTTP_SECRET"}))

    for field in FIELDS - {"SSH_PORT"}:
        require(isinstance(settings[field], str))


def validate_storage(settings):
    require(re.fullmatch(r"[a-f0-9]{32}", settings["R2_ACCOUNT_ID"]))
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", settings["R2_BUCKET"]))


def validate_hostname(hostname):
    require(len(hostname) <= 253 and "." in hostname)

    for label in hostname.split("."):
        require(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label))


def validate_credentials(settings):
    require(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", settings["REGISTRY_USERNAME"]))

    # bcrypt truncates above 72 bytes. Reject rather than silently weakening it.
    password = settings["REGISTRY_PASSWORD"]
    require(24 <= len(password.encode()) <= 72)

    for field in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "REGISTRY_PASSWORD"):
        value = settings[field]
        require(value and not any(ord(character) < 32 for character in value))
        require("REPLACE" not in value)


def validate_tls_paths(settings):
    for field in ("TLS_CERTIFICATE", "TLS_KEY"):
        path = Path(settings[field])
        require(path.is_absolute())
        require(path.is_file())


def validate_management_access(settings):
    require(type(settings["SSH_PORT"]) is int)
    require(1 <= settings["SSH_PORT"] <= 65535)
    ipaddress.ip_network(settings["MANAGEMENT_CIDR"], strict=True)
