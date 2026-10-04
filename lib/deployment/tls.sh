#!/usr/bin/env bash
# Operator-provided public CA certificates; never offer an insecure production mode.

prepare_tls() {
    local cert_file key_file hostname
    cert_file=$(run_python lib.configuration.settings certificate "$CONFIG_DIR/settings.json")
    key_file=$(run_python lib.configuration.settings key "$CONFIG_DIR/settings.json")
    hostname=$(run_python lib.configuration.settings hostname "$CONFIG_DIR/settings.json")
    [[ -f $cert_file && -f $key_file ]] || fail 'TLS certificate/key files are missing.'
    [[ $(stat -Lc '%u:%a' "$key_file") == 0:600 ]] || fail 'TLS key must be root-owned mode 0600.'
    openssl x509 -in "$cert_file" -noout -checkhost "$hostname" >/dev/null
    openssl x509 -in "$cert_file" -noout -checkend 604800 >/dev/null
    openssl x509 -in "$cert_file" -pubkey -noout | openssl pkey -pubin -outform DER >"$WORK_DIR/cert.pub"
    openssl pkey -in "$key_file" -passin pass: -pubout -outform DER >"$WORK_DIR/key.pub" 2>/dev/null
    cmp --silent "$WORK_DIR/cert.pub" "$WORK_DIR/key.pub" || fail 'TLS key does not match certificate.'
    install -m 0600 "$cert_file" "$CONFIG_DIR/tls.crt"
    install -m 0600 "$key_file" "$CONFIG_DIR/tls.key"
}
