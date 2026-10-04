#!/usr/bin/env bash
# R2 configuration and probes stay on the registry host, outside Apollo consumers.

validate_input() {
    local input_file=$1
    [[ -f $input_file && ! -L $input_file ]] || fail 'Input must be a regular JSON file.'
    [[ $(stat -c '%u:%a' "$input_file") == 0:600 ]] || fail 'Input must be root-owned mode 0600.'
    run_python lib.configuration.settings validate "$input_file"
}

prepare_configuration() {
    local input_file=$1
    if [[ -f $CONFIG_DIR/settings.json ]]; then
        # A repeat install must preserve every secret and operator configuration.
        run_python lib.configuration.settings compare "$input_file" "$CONFIG_DIR/settings.json"
        input_file="$CONFIG_DIR/settings.json"
    fi
    run_python lib.configuration.settings render "$input_file" "$WORK_DIR" \
        "$DEPLOY_ROOT/templates/config.yml"
    local filename
    # Persist the upload-signing secret first; recover missing files after interruption.
    for filename in settings.json config.yml client.json; do
        if [[ ! -f $CONFIG_DIR/$filename ]]; then
            install -m 0600 "$WORK_DIR/$filename" "$CONFIG_DIR/$filename"
        fi
    done
}
