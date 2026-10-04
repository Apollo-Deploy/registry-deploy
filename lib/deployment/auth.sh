#!/usr/bin/env bash
# Bcrypt authentication; plaintext is only read from a root-owned file/stdin.

prepare_authentication() {
    [[ ! -f $CONFIG_DIR/htpasswd ]] || return 0
    local username
    username=$(run_python lib.configuration.settings username "$CONFIG_DIR/settings.json")
    # -i avoids passwords in process arguments. Tool output contains only a username.
    run_python lib.configuration.settings password "$CONFIG_DIR/client.json" \
        | htpasswd -iBc "$WORK_DIR/htpasswd" "$username" >/dev/null 2>&1
    install -o root -g root -m 0600 "$WORK_DIR/htpasswd" "$CONFIG_DIR/htpasswd"
}
