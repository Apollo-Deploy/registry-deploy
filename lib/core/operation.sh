#!/usr/bin/env bash
# Own the deployment lock, private staging directory, and cleanup traps.

cleanup() {
    # Only remove the private directory created by this invocation.
    if [[ -n $WORK_DIR && -d $WORK_DIR ]]; then
        rm -rf -- "$WORK_DIR"
    fi
}

begin_operation() {
    require_root
    install -d -m 0700 /run/apollo-registry-deploy
    exec 9>/run/apollo-registry-deploy/lock
    flock -n 9 || fail 'Another registry operation is running.'
    WORK_DIR=$(mktemp -d /run/apollo-registry-deploy/work.XXXXXXXX)
    trap cleanup EXIT
    # Command text can contain secrets; report only the source and line.
    trap 'log "Operation failed at ${BASH_SOURCE[0]}:$LINENO (details suppressed)."' ERR
}
