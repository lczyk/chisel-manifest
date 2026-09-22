#!/usr/bin/env bash
set -e

UPSTREAM_REPO="https://github.com/canonical/chisel"
UPSTREAM_MODULE="github.com/canonical/chisel"
MIRROR_MODULE="github.com/canonical/chisel-manifest"
MIRRORED_PATHS=(
    public/jsonwall
    public/manifest
    internal/apachetestutil
)
LICENSE_HEADER="// SPDX-License-Identifier: Apache-2.0"
README="README.md"

function _usage() {
    printf 'usage: %s [-h] [--tracked] [REF]\n\n' "${0##*/}"
    printf 'Mirror %s from %s at REF (a tag or branch).\n' "${MIRRORED_PATHS[*]}" "${UPSTREAM_REPO}"
    printf 'REF defaults to the release %s says is tracked, which re-mirrors it in place.\n' "${README}"
    printf '\n  --tracked  print the tracked release and exit\n'
}

function _fail() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

function _tracked_ref() {
    local urls
    urls="$(grep -oE "${UPSTREAM_REPO#https://}/releases/tag/[^)]+" "${README}")" \
        || _fail "no upstream release link in ${README}"
    case "${urls}" in
        (*$'\n'*) _fail "more than one upstream release link in ${README}" ;;
    esac
    printf '%s\n' "${urls##*/}"
}

function _is_mirrored() {
    local pkg="$1" path
    for path in "${MIRRORED_PATHS[@]}"; do
        case "${pkg}/" in
            ("${path}/"*) return 0 ;;
        esac
    done
    return 1
}

# The mirror exists to carry these packages under Apache-2.0 without the
# AGPL-3.0 top-level license, so refuse anything that would break that.
function _check_upstream() {
    local src="$1" ref="$2" path others unlicensed imports pkg
    for path in "${MIRRORED_PATHS[@]}"; do
        [ -d "${src}/${path}" ] || _fail "upstream ${ref} has no ${path}"
    done

    others="$(cd "${src}" && find "${MIRRORED_PATHS[@]}" -type f ! -name '*.go')"
    [ -z "${others}" ] || _fail "upstream ${ref} has non-Go files, check their license: ${others//$'\n'/ }"

    unlicensed="$(cd "${src}" && grep -rLxF "${LICENSE_HEADER}" "${MIRRORED_PATHS[@]}")" || true
    [ -z "${unlicensed}" ] || _fail "upstream ${ref} has files without '${LICENSE_HEADER}': ${unlicensed//$'\n'/ }"

    imports="$(cd "${src}" && grep -rhoE "\"${UPSTREAM_MODULE}/[^\"]+\"" "${MIRRORED_PATHS[@]}" | tr -d '"' | sort -u)"
    while read -r pkg; do
        [ -z "${pkg}" ] || _is_mirrored "${pkg#"${UPSTREAM_MODULE}/"}" \
            || _fail "upstream ${ref} imports ${pkg}, which is not mirrored"
    done <<< "${imports}"
}

function _rewrite_imports() {
    local src="$1" file
    (cd "${src}" && find "${MIRRORED_PATHS[@]}" -type f -name '*.go') | while read -r file; do
        sed "s#\"${UPSTREAM_MODULE}/#\"${MIRROR_MODULE}/#g" "${src}/${file}" > "${src}/${file}.tmp"
        mv "${src}/${file}.tmp" "${src}/${file}"
    done
}

function _mirror() {
    local src="$1" path
    for path in "${MIRRORED_PATHS[@]}"; do
        rm -rf "${path}"
        mkdir -p "$(dirname "${path}")"
        cp -R "${src}/${path}" "${path}"
    done
}

function _set_tracked_ref() {
    local old="$1" new="$2" old_re
    if [ "${old}" = "${new}" ]; then
        return 0
    fi
    old_re="${old//./\\.}"
    sed -e "\#${UPSTREAM_REPO#https://}/releases/tag/#s#\`${old_re}\`#\`${new}\`#" \
        -e "s#/releases/tag/${old_re})#/releases/tag/${new})#" \
        "${README}" > "${README}.tmp"
    mv "${README}.tmp" "${README}"
    [ "$(_tracked_ref)" = "${new}" ] || _fail "could not update the tracked release in ${README}"
}

function main() {
    local ref tracked dirty src
    cd "$(dirname "$0")/../.."
    case "$1" in
        (-h|--help) _usage; exit 0 ;;
        (--tracked) _tracked_ref; exit 0 ;;
        (-*) _usage >&2; exit 2 ;;
    esac
    [ "$#" -le 1 ] || { _usage >&2; exit 2; }

    tracked="$(_tracked_ref)"
    ref="${1:-${tracked}}"
    case "${ref}" in
        (''|-*|*[!A-Za-z0-9._/-]*) _fail "invalid ref: '${ref}'" ;;
    esac

    dirty="$(git status --porcelain -- "${MIRRORED_PATHS[@]}" go.mod go.sum "${README}")"
    [ -z "${dirty}" ] || _fail "uncommitted changes in files this script overwrites:"$'\n'"${dirty}"

    src="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${src}'" EXIT
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "${ref}" "${UPSTREAM_REPO}" "${src}"

    _check_upstream "${src}" "${ref}"
    _rewrite_imports "${src}"
    _mirror "${src}"
    go mod tidy
    _set_tracked_ref "${tracked}" "${ref}"
    printf 'mirrored %s (was %s)\n' "${ref}" "${tracked}"
}

main "$@"
