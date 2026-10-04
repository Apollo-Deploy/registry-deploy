#!/usr/bin/env bash
# Package paths, common error reporting, and Python module execution. Never enable shell tracing here.
set -Eeuo pipefail
set +x
umask 077

DEPLOY_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# Shared paths are consumed by separately sourced lifecycle modules.
# shellcheck disable=SC2034
CONFIG_DIR=/etc/apollo-registry
# shellcheck disable=SC2034
STATE_DIR=/var/lib/apollo-registry
# shellcheck disable=SC2034
BINARY_DIR=/opt/apollo-registry
# shellcheck disable=SC2034
SERVICE=apollo-registry.service
# shellcheck disable=SC2034
WORK_DIR=

log() {
    printf '%s\n' "$*" >&2
}

fail() {
    log "ERROR: $*"
    exit 1
}

require_root() {
    [[ $EUID == 0 ]] || fail 'Run on the registry VPS as root.'
}

require_commands() {
    local command_name
    for command_name in "$@"; do
        command -v "$command_name" >/dev/null || fail "Missing command: $command_name"
    done
}

# Module execution starts from this root, so Python imports do not depend on caller cwd.
run_python() (
    cd -- "$DEPLOY_ROOT"
    exec python3 -m "$@"
)
