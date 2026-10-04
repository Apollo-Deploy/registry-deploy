#!/usr/bin/env bash
# Remove local service ownership only. No R2 client or remote-delete path exists here.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

# shellcheck source=lib/core/operation.sh
source "$DEPLOY_ROOT/lib/core/operation.sh"

[[ $# == 1 ]] || fail 'Usage: uninstall.sh --service-only | --purge-local'
case "$1" in
--service-only) ;;
--purge-local)
    read -r -p 'Type DELETE LOCAL REGISTRY CONFIG to remove local secrets/state: ' confirmation
    [[ $confirmation == 'DELETE LOCAL REGISTRY CONFIG' ]] || fail 'Local deletion cancelled.'
    ;;
*) fail 'Unknown uninstall option.' ;;
esac
begin_operation
if systemctl cat "$SERVICE" >/dev/null 2>&1; then
    systemctl disable --now "$SERVICE"
fi
if systemctl cat apollo-registry-upload-cleanup.timer >/dev/null 2>&1; then
    systemctl disable --now apollo-registry-upload-cleanup.timer
    systemctl stop apollo-registry-upload-cleanup.service
fi
rm -f /etc/systemd/system/apollo-registry.service \
    /etc/systemd/system/apollo-registry-upload-cleanup.service \
    /etc/systemd/system/apollo-registry-upload-cleanup.timer
systemctl daemon-reload
if [[ $1 == --purge-local ]]; then
    rm -rf -- "$CONFIG_DIR" "$STATE_DIR" "$BINARY_DIR"
fi
log 'Service removed. R2 objects are untouched. UFW rules and service account are retained.'
