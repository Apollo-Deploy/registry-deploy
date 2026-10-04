#!/usr/bin/env bash
# Dedicated VPS firewall. Fail before activation if SSH would be locked out.

configure_firewall() {
    local management_cidr ssh_port
    management_cidr=$(run_python lib.configuration.settings management "$CONFIG_DIR/settings.json")
    ssh_port=$(run_python lib.configuration.settings ssh-port "$CONFIG_DIR/settings.json")
    run_python lib.configuration.settings ssh-check "$CONFIG_DIR/settings.json"
    # Never reset existing rules silently: an unmanaged firewall needs operator review.
    if [[ ! -f $STATE_DIR/firewall-managed ]]; then
        ufw status | grep -Fx 'Status: inactive' >/dev/null || fail 'Review/disable existing UFW before first install.'
        [[ $(ufw show added | wc -l) -le 2 ]] || fail 'Existing UFW rules require operator review.'
        ufw default deny incoming >/dev/null
        ufw default allow outgoing >/dev/null
        ufw allow proto tcp from "$management_cidr" to any port "$ssh_port" >/dev/null
        ufw allow 443/tcp >/dev/null
        ufw --force enable >/dev/null
        touch "$STATE_DIR/firewall-managed"
    fi
    ufw status | grep -Fx 'Status: active' >/dev/null || fail 'Managed firewall is inactive.'
}
