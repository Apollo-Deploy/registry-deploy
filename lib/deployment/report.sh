#!/usr/bin/env bash
# Emit client connection values only after authenticated deployment verification.

report_success() {
    local hostname
    hostname=$(run_python lib.configuration.settings hostname "$CONFIG_DIR/settings.json")
    cat <<REPORT
Registry deployed successfully

Registry:
https://$hostname

BuildKit cache:
type=registry,ref=$hostname/apollo/build-cache

Artifact repository:
$hostname/apollo/artifacts

Health:
PASS

R2:
CONNECTED

Authentication:
ENABLED

TLS:
VALID

REGISTRY_URL=https://$hostname
BUILDKIT_CACHE_EXPORT=type=registry,ref=$hostname/apollo/build-cache,mode=max
BUILDKIT_CACHE_IMPORT=type=registry,ref=$hostname/apollo/build-cache
REPORT
}
