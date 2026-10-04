#!/usr/bin/env bash
# Release integrity and atomic activation. Digests are pinned in this reviewed package.
# shellcheck disable=SC2034
DISTRIBUTION_VERSION=3.1.2

release_checksum() {
    case "$1:$RELEASE_ARCH" in
    3.1.2:amd64) printf '%s' 40df2224d410f72ae425c3371873b078bbdbda3b8b612be9571f0e6751f3acc8 ;;
    3.1.2:arm64) printf '%s' 09d26f88d2c0f161bd1b8bfc6c123571cc3d291dcca8af5477b3cacc4ec95e73 ;;
    *) fail 'Version/architecture has no reviewed checksum. Update the release table first.' ;;
    esac
}

prepare_release() {
    local version=$1 checksum asset release_path
    checksum=$(release_checksum "$version")
    asset="registry_${version}_linux_${RELEASE_ARCH}.tar.gz"
    release_path="$BINARY_DIR/releases/$version"
    curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
        --retry 3 --connect-timeout 15 --max-time 300 --location \
        "https://github.com/distribution/distribution/releases/download/v$version/$asset" \
        --output "$WORK_DIR/release.tar.gz"
    printf '%s  %s\n' "$checksum" "$WORK_DIR/release.tar.gz" | sha256sum --check --status
    # Extract only the expected executable, never arbitrary archive paths.
    tar -xzf "$WORK_DIR/release.tar.gz" -C "$WORK_DIR" registry
    [[ $("$WORK_DIR/registry" --version | awk '{print $NF}') == "$version" ]] \
        || fail 'Verified binary reports an unexpected version.'
    install -d -m 0755 "$release_path"
    if [[ -e $release_path/registry ]]; then
        cmp --silent "$WORK_DIR/registry" "$release_path/registry" || fail 'Installed release was modified.'
    else
        install -o root -g root -m 0755 "$WORK_DIR/registry" "$release_path/registry"
    fi
}

activate_binary() {
    # Stage beside the target: /run may be a different filesystem, where mv is not atomic.
    ln -sfn "$1" "$BINARY_DIR/current.next"
    mv -Tf "$BINARY_DIR/current.next" "$BINARY_DIR/current"
}
