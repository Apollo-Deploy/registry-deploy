#!/usr/bin/env bash
# Real end-to-end qualification; restart and dedicated BuildKit pruning need explicit flags.
set -Eeuo pipefail

# shellcheck source=lib/core/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/core/common.sh"

# shellcheck source=lib/core/operation.sh
source "$DEPLOY_ROOT/lib/core/operation.sh"

[[ $# == 2 && $1 == --allow-restart && $2 == --allow-buildkit-prune ]] \
    || fail 'Usage: qualify.sh --allow-restart --allow-buildkit-prune (dedicated BuildKit worker only)'
begin_operation
require_commands python3 buildctl systemctl
[[ -n ${BUILDKIT_HOST:-} ]] || fail 'Set BUILDKIT_HOST to an isolated local/unix BuildKit worker.'
[[ $BUILDKIT_HOST == unix://* ]] || fail 'Qualification accepts local unix BuildKit sockets only.'
[[ ${BUILDKIT_BASE_IMAGE:-} =~ @sha256:[a-f0-9]{64}$ ]] || fail 'Set BUILDKIT_BASE_IMAGE to a pinned Linux image with /bin/sh.'
"$DEPLOY_ROOT/healthcheck.sh" --json
run_python lib.qualification.run "$WORK_DIR"
run_python lib.qualification.buildkit "$WORK_DIR"
log 'PRODUCTION QUALIFICATION PASS (see JSON measurements above).'
