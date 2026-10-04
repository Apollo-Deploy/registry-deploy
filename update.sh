#!/usr/bin/env bash
# Transactional binary-only update, with health-based rollback and unchanged secrets.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

# shellcheck source=lib/core/operation.sh
source "$DEPLOY_ROOT/lib/core/operation.sh"

# shellcheck source=lib/deployment/system.sh
source "$DEPLOY_ROOT/lib/deployment/system.sh"

# shellcheck source=lib/deployment/distribution.sh
source "$DEPLOY_ROOT/lib/deployment/distribution.sh"

# shellcheck source=lib/verification/health.sh
source "$DEPLOY_ROOT/lib/verification/health.sh"

[[ $# == 1 && $1 =~ ^3\.[0-9]+\.[0-9]+$ ]] || fail 'Usage: update.sh REVIEWED_VERSION'
begin_operation
validate_platform
require_commands curl sha256sum tar python3
[[ -L $BINARY_DIR/current ]] || fail 'Registry is not installed.'
wait_for_health || fail 'Current release is not healthy; update refused.'
previous_binary=$(readlink -f "$BINARY_DIR/current")
prepare_release "$1"

rollback() {
    # Roll back even when restart or a signal fails between stop and verification.
    trap - ERR INT TERM
    activate_binary "$previous_binary"
    systemctl restart "$SERVICE"
    wait_for_health || fail 'Rollback also failed; operator intervention required.'
    fail 'Update failed; previous binary restored and healthy.'
}
trap rollback ERR INT TERM
systemctl stop "$SERVICE"
activate_binary "$BINARY_DIR/releases/$1/registry"
systemctl start "$SERVICE"
verify_installation
trap - ERR INT TERM
log "Distribution $1 is healthy. Previous binary: $previous_binary"
