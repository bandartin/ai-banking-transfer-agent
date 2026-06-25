#!/bin/bash

is_valid_awx_sdk_root() {
    local sdk_root="$1"
    [ -d "$sdk_root/awx_core/src/awx" ] || return 1
    [ -d "$sdk_root/awx_resources/src/awx" ] || return 1
    [ -d "$sdk_root/awx_observability/src/awx" ] || return 1
    return 0
}

find_awx_sdk_root() {
    local current_dir="${1:-$PWD}"

    if [ -n "${AWX_SDK_ROOT:-}" ] && is_valid_awx_sdk_root "$AWX_SDK_ROOT"; then
        printf '%s' "$AWX_SDK_ROOT"
        return 0
    fi

    while [ -n "$current_dir" ] && [ "$current_dir" != "/" ]; do
        if is_valid_awx_sdk_root "$current_dir/python-user-sdk"; then
            printf '%s' "$current_dir/python-user-sdk"
            return 0
        fi
        current_dir="$(dirname "$current_dir")"
    done

    local fixed_candidates=(
        "/project/work/python-user-sdk"
        "/workspace/python-user-sdk"
        "/home/user/idea-project/python-user-sdk"
    )
    local candidate
    for candidate in "${fixed_candidates[@]}"; do
        if is_valid_awx_sdk_root "$candidate"; then
            printf '%s' "$candidate"
            return 0
        fi
    done

    return 1
}

find_system_awx_site_packages() {
    python3 - <<'PY'
import importlib.util
import os

spec = importlib.util.find_spec("awx")
if not spec or not spec.submodule_search_locations:
    raise SystemExit(0)

seen = set()
for awx_dir in spec.submodule_search_locations:
    parent = os.path.dirname(awx_dir.rstrip("/"))
    if parent and parent not in seen:
        seen.add(parent)
        print(parent)
PY
}

prepend_awx_sdk_pythonpath() {
    local script_dir="${1:-$PWD}"
    local sdk_root
    sdk_root="$(find_awx_sdk_root "$script_dir" || true)"

    local local_sdk_pythonpath=""
    if [ -n "$sdk_root" ]; then
        local sdk_paths=(
            "$sdk_root/awx_core/src"
            "$sdk_root/awx_resources/src"
            "$sdk_root/awx_observability/src"
        )
        local path_entry

        for path_entry in "${sdk_paths[@]}"; do
            if [ -d "$path_entry" ]; then
                if [ -n "$local_sdk_pythonpath" ]; then
                    local_sdk_pythonpath="${local_sdk_pythonpath}:$path_entry"
                else
                    local_sdk_pythonpath="$path_entry"
                fi
            fi
        done
    fi

    if [ -z "$local_sdk_pythonpath" ]; then
        local system_site_packages
        system_site_packages="$(find_system_awx_site_packages | paste -sd: -)"
        if [ -n "$system_site_packages" ]; then
            local_sdk_pythonpath="$system_site_packages"
        else
            return 0
        fi
    fi

    if [ -n "${PYTHONPATH:-}" ]; then
        export PYTHONPATH="${local_sdk_pythonpath}:$PYTHONPATH"
    else
        export PYTHONPATH="$local_sdk_pythonpath"
    fi
}
