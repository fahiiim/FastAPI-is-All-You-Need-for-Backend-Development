"""Prepare the repository's publishable documentation for MkDocs."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE_ROOT = ROOT / ".mkdocs-source"
DOCUMENTATION_DIRECTORIES = (
    "architecture",
    "decision-guides",
    "docs",
    "interview",
    "resources",
)
EXAMPLE_READMES = (
    "examples/README.md",
    "examples/basic-crud/README.md",
    "examples/production-api/README.md",
    "examples/distributed-api/README.md",
    "examples/ai-api/README.md",
)
ROOT_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "backend-project-structure.md",
)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> None:
    if STAGE_ROOT.resolve().parent != ROOT.resolve():
        raise RuntimeError("Refusing to prepare documentation outside the repository root")

    shutil.rmtree(STAGE_ROOT, ignore_errors=True)
    stale_files = [path for path in STAGE_ROOT.rglob("*") if path.is_file()]
    if stale_files:
        raise RuntimeError(f"Could not clear generated file: {stale_files[0]}")
    STAGE_ROOT.mkdir(exist_ok=True)

    copied = 0
    for relative_name in ROOT_FILES:
        copy_file(ROOT / relative_name, STAGE_ROOT / relative_name)
        copied += 1

    for directory_name in DOCUMENTATION_DIRECTORIES:
        source_root = ROOT / directory_name
        for source in sorted(source_root.rglob("*.md")):
            destination = STAGE_ROOT / source.relative_to(ROOT)
            copy_file(source, destination)
            copied += 1

    for relative_name in EXAMPLE_READMES:
        copy_file(ROOT / relative_name, STAGE_ROOT / relative_name)
        copied += 1

    print(f"Prepared {copied} documentation files for MkDocs.")


if __name__ == "__main__":
    main()
