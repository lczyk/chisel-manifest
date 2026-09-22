#!/usr/bin/env python3
"""
Unit tests for apply_upstream.py
"""

import pytest

import sys
import os
import shutil
from pathlib import Path
from textwrap import dedent

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import apply_upstream

HEADER = apply_upstream.LICENSE_HEADER


def write_upstream(root: Path, files: dict[str, str] | None = None) -> Path:
    """Lay out a minimal upstream tree with every mirrored package, plus any extra files."""
    base = {
        "go.mod": "module github.com/canonical/chisel\n\ngo 1.25.8\n",
        "public/jsonwall/jsonwall.go": f"{HEADER}\n\npackage jsonwall\n",
        "public/manifest/manifest.go": dedent(f"""
            {HEADER}

            package manifest

            import (
            \t"github.com/canonical/chisel/public/jsonwall"
            )
        """).lstrip(),
        "internal/apachetestutil/manifest.go": dedent(f"""
            {HEADER}

            package apachetestutil

            import "github.com/canonical/chisel/public/manifest"
        """).lstrip(),
    }
    for name, text in {**base, **(files or {})}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


class TestCheckCheckout:
    def test_ok(self, tmp_path: Path) -> None:
        apply_upstream.check_checkout(write_upstream(tmp_path))

    @pytest.mark.parametrize(
        "go_mod", [None, "module github.com/canonical/chisel-manifest\n"]
    )
    def test_not_chisel(self, tmp_path: Path, go_mod: str | None) -> None:
        if go_mod is not None:
            (tmp_path / "go.mod").write_text(go_mod)
        with pytest.raises(SystemExit, match="not a checkout"):
            apply_upstream.check_checkout(tmp_path)


class TestCheckUpstream:
    def test_ok(self, tmp_path: Path) -> None:
        apply_upstream.check_upstream(write_upstream(tmp_path))

    def test_mirrored_subpackage(self, tmp_path: Path) -> None:
        src = write_upstream(
            tmp_path,
            {
                "public/manifest/sub/sub.go": f'{HEADER}\n\npackage sub\n\nimport _ "github.com/canonical/chisel/public/manifest"\n'
            },
        )
        apply_upstream.check_upstream(src)

    @pytest.mark.parametrize(
        "files, problem",
        [
            (
                {"public/manifest/testdata/a.json": "{}"},
                "public/manifest/testdata/a.json is not a Go file",
            ),
            (
                {"public/manifest/extra.go": "package manifest\n"},
                "public/manifest/extra.go does not start with",
            ),
            (
                {"public/manifest/extra.go": f"package manifest\n\n{HEADER}\n"},
                "public/manifest/extra.go does not start with",
            ),
            (
                {
                    "public/manifest/extra.go": f'{HEADER}\n\npackage manifest\n\nimport _ "github.com/canonical/chisel/internal/testutil"\n'
                },
                "imports github.com/canonical/chisel/internal/testutil, which is not mirrored",
            ),
            (
                {
                    "public/manifest/extra.go": f'{HEADER}\n\npackage manifest\n\nimport _ "github.com/canonical/chisel/public/manifestutil"\n'
                },
                "imports github.com/canonical/chisel/public/manifestutil, which is not mirrored",
            ),
        ],
    )
    def test_problem(self, tmp_path: Path, files: dict[str, str], problem: str) -> None:
        src = write_upstream(tmp_path, files)
        with pytest.raises(SystemExit, match="cannot be mirrored") as e:
            apply_upstream.check_upstream(src)
        assert problem in str(e.value)

    def test_missing_path(self, tmp_path: Path) -> None:
        src = write_upstream(tmp_path)
        shutil.rmtree(src / "internal/apachetestutil")
        with pytest.raises(SystemExit) as e:
            apply_upstream.check_upstream(src)
        assert "internal/apachetestutil does not exist" in str(e.value)

    def test_reports_all_problems(self, tmp_path: Path) -> None:
        src = write_upstream(
            tmp_path,
            {"public/jsonwall/a.txt": "", "public/manifest/b.go": "package manifest\n"},
        )
        with pytest.raises(SystemExit) as e:
            apply_upstream.check_upstream(src)
        assert "public/jsonwall/a.txt" in str(e.value)
        assert "public/manifest/b.go" in str(e.value)


class TestRewriteImports:
    def test_basic(self) -> None:
        text = dedent("""
            import (
            \t"github.com/canonical/chisel/internal/apachetestutil"
            \t"github.com/canonical/chisel/public/manifest"
            )
        """)
        assert apply_upstream.rewrite_imports(text) == text.replace(
            "canonical/chisel/", "canonical/chisel-manifest/"
        )

    @pytest.mark.parametrize(
        "text",
        [
            '"github.com/canonical/chisel-manifest/public/manifest"',
            "// see https://github.com/canonical/chisel/issues",
            '"gopkg.in/check.v1"',
        ],
    )
    def test_untouched(self, text: str) -> None:
        assert apply_upstream.rewrite_imports(text) == text


class TestApply:
    @pytest.fixture
    def upstream(self, tmp_path: Path) -> Path:
        return write_upstream(tmp_path / "upstream")

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        """A mirror with a file upstream no longer has"""
        root = tmp_path / "mirror"
        (root / "public/manifest").mkdir(parents=True)
        (root / "public/manifest/stale.go").write_text("package manifest\n")
        (root / "README.md").write_text("# Chisel Manifest\n")
        return root

    def test_basic(self, repo: Path, upstream: Path) -> None:
        apply_upstream.apply(repo, upstream)

        assert not (repo / "public/manifest/stale.go").exists()
        manifest = (repo / "public/manifest/manifest.go").read_text()
        assert '"github.com/canonical/chisel-manifest/public/jsonwall"' in manifest
        assert sorted(p.name for p in repo.iterdir()) == [
            "README.md",
            "internal",
            "public",
        ], "only the mirrored packages are touched"
        assert (repo / "README.md").read_text() == "# Chisel Manifest\n"

    def test_bad_upstream_leaves_mirror_alone(self, repo: Path, upstream: Path) -> None:
        (upstream / "public/manifest/extra.go").write_text("package manifest\n")
        with pytest.raises(SystemExit, match="cannot be mirrored"):
            apply_upstream.apply(repo, upstream)
        assert (repo / "public/manifest/stale.go").exists()
