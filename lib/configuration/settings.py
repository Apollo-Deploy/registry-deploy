#!/usr/bin/env python3
"""Command interface for validated settings; secret values never enter error diagnostics."""

import ipaddress
import json
import os
import sys
from pathlib import Path

from lib.configuration.render import render
from lib.configuration.validation import FIELDS, require, validate


def main():
    action, filename, *arguments = sys.argv[1:]
    settings = json.loads(Path(filename).read_text())
    if action == "validate":
        validate(settings)
    elif action == "compare":
        existing = json.loads(Path(arguments[0]).read_text())
        require(all(existing.get(key) == settings.get(key) for key in FIELDS))
    elif action == "render":
        render(settings, *arguments)
    elif action == "ssh-check":
        connection = os.environ.get("SSH_CONNECTION")
        if connection:
            peer, _, _, port = connection.split()
            require(ipaddress.ip_address(peer) in ipaddress.ip_network(settings["MANAGEMENT_CIDR"]))
            require(int(port) == settings["SSH_PORT"])
    else:
        key = {
            "hostname": "REGISTRY_HOSTNAME",
            "username": "REGISTRY_USERNAME",
            "certificate": "TLS_CERTIFICATE",
            "key": "TLS_KEY",
            "management": "MANAGEMENT_CIDR",
            "ssh-port": "SSH_PORT",
            "password": "password",
        }[action]
        print(settings[key])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Validation exceptions can quote secrets; do not print their bodies.
        print(
            "Configuration validation failed; check required fields, permissions, and values.",
            file=sys.stderr,
        )
        sys.exit(1)
