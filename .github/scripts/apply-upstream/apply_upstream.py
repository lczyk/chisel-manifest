#!/usr/bin/env python3
"""
Apply a checkout of [chisel](https://github.com/canonical/chisel) onto this mirror, e.g.:

    git clone --depth=1 --branch=v1.5.0 https://github.com/canonical/chisel /tmp/chisel
    .github/scripts/apply-upstream/apply_upstream.py /tmp/chisel
    go mod tidy

The mirrored packages are first checked to still be safe to carry under Apache-2.0: every file must be a
Go file with an Apache-2.0 SPDX header, and must not import any upstream package which is not mirrored.
They then replace the local copies, with their import paths rewritten to this module. The result is left
in the working tree, so any difference from the mirror shows up in `git status`.
"""

from __future__ import annotations

from pathlib import Path

import argparse
import re
import shutil
import sys

UPSTREAM_MODULE = "github.com/canonical/chisel"
MIRROR_MODULE = "github.com/canonical/chisel-manifest"
MIRRORED_PATHS: tuple[str, ...] = (
    "public/jsonwall",
    "public/manifest",
    "internal/apachetestutil",
)
LICENSE_HEADER = "// SPDX-License-Identifier: Apache-2.0"

REPO_ROOT = Path(__file__).resolve().parents[3]

_IMPORT_RE = re.compile(r'"' + re.escape(UPSTREAM_MODULE) + r'/([^"]+)"')


def check_checkout(src: Path) -> None:
    go_mod = src / "go.mod"
    module = go_mod.read_text().split("\n", 1)[0] if go_mod.is_file() else ""
    if module != f"module {UPSTREAM_MODULE}":
        sys.exit(f"{src} is not a checkout of {UPSTREAM_MODULE}")


def check_upstream(src: Path) -> None:
    """The mirror exists to carry these packages under Apache-2.0 without chisel's AGPL-3.0 top-level
    license, so refuse anything that would break that."""
    problems: list[str] = []
    for path in MIRRORED_PATHS:
        if not (src / path).is_dir():
            problems.append(f"{path} does not exist")
            continue
        for file in sorted(p for p in (src / path).rglob("*") if p.is_file()):
            name = file.relative_to(src)
            if file.suffix != ".go":
                problems.append(f"{name} is not a Go file, check its license")
                continue
            text = file.read_bytes().decode()
            if text.split("\n", 1)[0] != LICENSE_HEADER:
                problems.append(f"{name} does not start with '{LICENSE_HEADER}'")
            for pkg in _IMPORT_RE.findall(text):
                if not is_mirrored(pkg):
                    problems.append(
                        f"{name} imports {UPSTREAM_MODULE}/{pkg}, which is not mirrored"
                    )
    if problems:
        sys.exit("upstream cannot be mirrored:\n  " + "\n  ".join(problems))


def is_mirrored(pkg: str) -> bool:
    return any(pkg == path or pkg.startswith(f"{path}/") for path in MIRRORED_PATHS)


def rewrite_imports(text: str) -> str:
    return text.replace(f'"{UPSTREAM_MODULE}/', f'"{MIRROR_MODULE}/')


def mirror(src: Path, dst: Path) -> None:
    """Replace the mirrored packages in dst with the ones in src, rewriting their imports."""
    for path in MIRRORED_PATHS:
        shutil.rmtree(dst / path, ignore_errors=True)
        for file in (src / path).rglob("*.go"):
            target = dst / file.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rewrite_imports(file.read_bytes().decode()).encode())


def apply(root: Path, src: Path) -> None:
    """Apply the upstream checkout at src onto the mirror at root."""
    check_checkout(src)
    check_upstream(src)
    mirror(src, root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("upstream", type=Path, help="checkout of chisel")
    args = parser.parse_args()

    apply(REPO_ROOT, args.upstream.resolve())


if __name__ == "__main__":
    main()
