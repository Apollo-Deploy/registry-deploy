#!/usr/bin/env bash
# Install a standalone registry. Existing credentials and configuration are immutable here.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

# shellcheck source=lib/core/operation.sh
source "$DEPLOY_ROOT/lib/core/operation.sh"

# shellcheck source=lib/deployment/system.sh
source "$DEPLOY_ROOT/lib/deployment/system.sh"

# shellcheck source=lib/deployment/distribution.sh
source "$DEPLOY_ROOT/lib/deployment/distribution.sh"

# shellcheck source=lib/deployment/r2.sh
source "$DEPLOY_ROOT/lib/deployment/r2.sh"

# shellcheck source=lib/deployment/auth.sh
source "$DEPLOY_ROOT/lib/deployment/auth.sh"

# shellcheck source=lib/deployment/tls.sh
source "$DEPLOY_ROOT/lib/deployment/tls.sh"

# shellcheck source=lib/deployment/firewall.sh
source "$DEPLOY_ROOT/lib/deployment/firewall.sh"

# shellcheck source=lib/deployment/report.sh
source "$DEPLOY_ROOT/lib/deployment/report.sh"

# shellcheck source=lib/verification/health.sh
source "$DEPLOY_ROOT/lib/verification/health.sh"

[[ $# == 1 ]] || fail 'Usage: install.sh /root/registry-settings.json'

begin_operation
validate_platform
install_packages
validate_input "$1"

prepare_directories
prepare_configuration "$1"
prepare_authentication

if [[ ! -f $CONFIG_DIR/tls.crt || ! -f $CONFIG_DIR/tls.key ]]; then
    prepare_tls
fi

run_python lib.verification.health r2-check

if [[ ! -L $BINARY_DIR/current ]]; then
    prepare_release "$DISTRIBUTION_VERSION"
    activate_binary "$BINARY_DIR/releases/$DISTRIBUTION_VERSION/registry"
fi

install_package_files
configure_firewall

systemctl enable --now apollo-registry-upload-cleanup.timer
systemctl enable "$SERVICE" >/dev/null
# An idempotent install does not interrupt an already active registry.
systemctl start "$SERVICE"

verify_installation
report_success
