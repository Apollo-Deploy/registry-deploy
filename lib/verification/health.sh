#!/usr/bin/env bash
# Verify the running service through the same OCI boundary as external clients.

wait_for_health() {
    local attempt
    for attempt in {1..12}; do
        log "Checking registry health (attempt $attempt/12)."
        if "$DEPLOY_ROOT/healthcheck.sh" --json >"$WORK_DIR/health.json" 2>/dev/null; then
            return 0
        fi
        sleep 5
    done
    log 'Health failed; inspect the sanitized service journal.'
    return 1
}

verify_installation() {
    wait_for_health
    run_python lib.verification.health smoke
}
