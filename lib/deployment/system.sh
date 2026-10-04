#!/usr/bin/env bash
# Platform support and local service ownership; no remote storage mutations.

validate_platform() {
    [[ $(uname -s) == Linux ]] || fail 'Only Linux VPS installations are supported.'
    # shellcheck source=/dev/null
    source /etc/os-release
    case "$ID:$VERSION_ID" in
    debian:12 | debian:13 | ubuntu:24.04) ;;
    *) fail 'Supported: Debian 12/13 and Ubuntu 24.04.' ;;
    esac
    # shellcheck disable=SC2034
    case $(uname -m) in
    x86_64) RELEASE_ARCH=amd64 ;;
    aarch64 | arm64) RELEASE_ARCH=arm64 ;;
    *) fail 'Supported CPU architectures: x86_64 and arm64.' ;;
    esac
    [[ $(ps -p 1 -o comm=) == systemd ]] || fail 'systemd must be PID 1.'
}

install_packages() {
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl apache2-utils openssl python3 python3-yaml \
        python3-boto3 ufw util-linux
}

prepare_directories() {
    if ! getent passwd apollo-registry >/dev/null; then
        useradd --system --user-group --home-dir "$STATE_DIR" --shell /usr/sbin/nologin apollo-registry
    fi
    [[ $(getent passwd apollo-registry | cut -d: -f7) == /usr/sbin/nologin ]] \
        || fail 'Existing service account must have a non-login shell.'
    [[ $(id -u apollo-registry) != 0 ]] || fail 'Service account must not be root.'
    install -d -o root -g root -m 0700 "$CONFIG_DIR" "$STATE_DIR"
    install -d -o root -g root -m 0755 "$BINARY_DIR/releases" "$BINARY_DIR/deploy"
}

install_package_files() {
    # The installed scripts are independent of the checkout used for installation.
    if [[ $DEPLOY_ROOT != "$BINARY_DIR/deploy" ]]; then
        cp -R "$DEPLOY_ROOT/lib" "$DEPLOY_ROOT/templates" "$BINARY_DIR/deploy/"

        local entry
        for entry in install update uninstall healthcheck qualify renew-tls; do
            install -m 0755 "$DEPLOY_ROOT/$entry.sh" "$BINARY_DIR/deploy/$entry.sh"
        done
    fi

    install -m 0644 "$DEPLOY_ROOT/templates/apollo-registry.service" \
        /etc/systemd/system/apollo-registry.service
    install -d -m 0755 /etc/systemd/journald@apollo-registry.conf.d
    install -m 0644 "$DEPLOY_ROOT/templates/journal.conf" \
        /etc/systemd/journald@apollo-registry.conf.d/retention.conf
    install -m 0644 "$DEPLOY_ROOT/templates/apollo-registry-upload-cleanup.service" /etc/systemd/system/
    install -m 0644 "$DEPLOY_ROOT/templates/apollo-registry-upload-cleanup.timer" /etc/systemd/system/
    systemctl daemon-reload
}
