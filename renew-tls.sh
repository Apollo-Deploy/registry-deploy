#!/usr/bin/env bash
# Apply operator-renewed certificates transactionally; systemd snapshots require restart.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

# shellcheck source=lib/core/operation.sh
source "$DEPLOY_ROOT/lib/core/operation.sh"

# shellcheck source=lib/deployment/tls.sh
source "$DEPLOY_ROOT/lib/deployment/tls.sh"

# shellcheck source=lib/verification/health.sh
source "$DEPLOY_ROOT/lib/verification/health.sh"

[[ $# == 0 ]] || fail 'Usage: renew-tls.sh (uses persisted certificate source paths)'
begin_operation
[[ -f $CONFIG_DIR/tls.crt && -f $CONFIG_DIR/tls.key ]] || fail 'Registry TLS is not installed.'
cp "$CONFIG_DIR/tls.crt" "$WORK_DIR/previous.crt"
cp "$CONFIG_DIR/tls.key" "$WORK_DIR/previous.key"

rollback_tls() {
    trap - ERR INT TERM
    install -m 0600 "$WORK_DIR/previous.crt" "$CONFIG_DIR/tls.crt"
    install -m 0600 "$WORK_DIR/previous.key" "$CONFIG_DIR/tls.key"
    systemctl restart "$SERVICE"
    wait_for_health || fail 'TLS rollback failed; operator intervention required.'
    fail 'New TLS failed; previous certificate/key restored.'
}
trap rollback_tls ERR INT TERM
prepare_tls
systemctl restart "$SERVICE"
wait_for_health
trap - ERR INT TERM
log 'Renewed TLS is active and healthy.'
