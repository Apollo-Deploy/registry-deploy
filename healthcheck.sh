#!/usr/bin/env bash
# Machine-readable HTTPS/auth/R2 health; fails closed and emits no exception bodies.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

[[ $# == 0 || ($# == 1 && $1 == --json) ]] || fail 'Usage: healthcheck.sh [--json]'
require_root
if ! systemctl is-active --quiet "$SERVICE"; then
    printf '%s\n' '{"health":"FAIL","check":"systemd"}'
    exit 1
fi
# A fixed tiny artifact checks writes/reads without producing unbounded health data.
run_python lib.verification.health health
