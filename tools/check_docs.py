"""Repository-local documentation quality checks.

The checker has no third-party dependencies so it can run in a clean checkout.
It validates local Markdown links, fenced code blocks, Python syntax, headings, and
the repository's writing constraints.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FEATURE_VERSION = (3, 11)
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".mkdocs-source",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".site-build",
    ".venv",
    ".wrangler",
    "dist",
    "node_modules",
    "site",
    "__pycache__",
}
EXCLUDED_DIRECTORIES = {ROOT / "hosting" / "public"}
FORBIDDEN_CHARACTERS = {
    "\u2013": "Unicode en dash",
    "\u2014": "Unicode em dash",
}
FORBIDDEN_PHRASES = {
    "TODO": "unfinished TODO marker",
    "TBD": "unfinished TBD marker",
    "FIXME": "unfinished FIXME marker",
    "\u00e2\u20ac\u201d": "mis-decoded long dash",
    "\u00e2\u20ac\u201c": "mis-decoded dash",
    "In today's fast-paced world": "generic marketing introduction",
    "game-changer": "marketing phrase",
}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^```([^\s`]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HTML_ANCHOR_RE = re.compile(r"<a\s+(?:name|id)=[\"']([^\"']+)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        relative = self.path.relative_to(ROOT)
        return f"{relative}:{self.line}: {self.message}"


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in EXCLUDED_PARTS for part in path.parts)
        and not any(path.is_relative_to(directory) for directory in EXCLUDED_DIRECTORIES)
    )


def github_slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_~]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def anchors_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    duplicates: Counter[str] = Counter()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if match := HEADING_RE.match(line):
            base = github_slug(match.group(2))
            number = duplicates[base]
            anchors.add(base if number == 0 else f"{base}-{number}")
            duplicates[base] += 1
        anchors.update(HTML_ANCHOR_RE.findall(line))
    return anchors


def looks_like_emoji(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x26FF
        or 0x2700 <= codepoint <= 0x27BF
    )


def resolve_link(source: Path, raw_target: str) -> tuple[Path, str]:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    parsed = urlsplit(target)
    path_text = unquote(parsed.path)
    destination = source if not path_text else (source.parent / path_text).resolve()
    if destination.is_dir():
        destination = destination / "README.md"
    return destination, unquote(parsed.fragment)


def inspect_file(path: Path, anchor_cache: dict[Path, set[str]]) -> tuple[list[Problem], int, int]:
    problems: list[Problem] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    python_blocks = 0
    external_links = 0

    if path.name != "README.md" and len(text.split()) < 40:
        problems.append(Problem(path, 1, "Markdown file has too little substantive content"))

    for forbidden, description in FORBIDDEN_CHARACTERS.items():
        for line_number, line in enumerate(lines, 1):
            if forbidden in line:
                problems.append(Problem(path, line_number, f"contains {description}"))

    for phrase, description in FORBIDDEN_PHRASES.items():
        for line_number, line in enumerate(lines, 1):
            if phrase in line:
                problems.append(Problem(path, line_number, f"contains {description}: {phrase!r}"))

    for line_number, line in enumerate(lines, 1):
        if any(looks_like_emoji(character) for character in line):
            problems.append(Problem(path, line_number, "contains an emoji or pictograph character"))

    in_fence = False
    fence_language = ""
    fence_start = 0
    fence_lines: list[str] = []
    previous_heading = 0

    for line_number, line in enumerate(lines, 1):
        if match := FENCE_RE.match(line):
            if not in_fence:
                in_fence = True
                fence_language = match.group(1).lower()
                fence_start = line_number
                fence_lines = []
            else:
                if fence_language in {"python", "py"}:
                    python_blocks += 1
                    try:
                        ast.parse("\n".join(fence_lines), feature_version=PYTHON_FEATURE_VERSION)
                    except SyntaxError as exc:
                        detail = exc.msg
                        problems.append(
                            Problem(path, fence_start + (exc.lineno or 1), f"invalid Python fence: {detail}")
                        )
                in_fence = False
                fence_language = ""
                fence_lines = []
            continue

        if in_fence:
            fence_lines.append(line)
            continue

        if heading := HEADING_RE.match(line):
            level = len(heading.group(1))
            if previous_heading and level > previous_heading + 1:
                problems.append(
                    Problem(path, line_number, f"heading jumps from level {previous_heading} to {level}")
                )
            previous_heading = level

        for raw_target in LINK_RE.findall(line):
            target = raw_target.split(maxsplit=1)[0]
            scheme = urlsplit(target.strip("<>")).scheme.lower()
            if scheme in {"http", "https"}:
                external_links += 1
                continue
            if scheme or target.startswith(("mailto:", "#")):
                if target.startswith("#"):
                    fragment = unquote(target[1:])
                    if fragment and fragment not in anchor_cache[path]:
                        problems.append(Problem(path, line_number, f"missing local anchor #{fragment}"))
                continue

            destination, fragment = resolve_link(path, target)
            try:
                destination.relative_to(ROOT)
            except ValueError:
                problems.append(Problem(path, line_number, f"local link escapes repository: {target}"))
                continue
            if not destination.is_file():
                problems.append(Problem(path, line_number, f"broken local link: {target}"))
                continue
            if fragment and destination.suffix.lower() == ".md":
                if destination not in anchor_cache:
                    anchor_cache[destination] = anchors_for(destination)
                if fragment not in anchor_cache[destination]:
                    problems.append(
                        Problem(path, line_number, f"missing anchor #{fragment} in {destination.relative_to(ROOT)}")
                    )

    if in_fence:
        problems.append(Problem(path, fence_start, "unclosed fenced code block"))

    return problems, python_blocks, external_links


def main() -> int:
    files = markdown_files()
    anchor_cache = {path: anchors_for(path) for path in files}
    problems: list[Problem] = []
    python_blocks = 0
    external_links = 0

    for path in files:
        file_problems, file_python_blocks, file_external_links = inspect_file(path, anchor_cache)
        problems.extend(file_problems)
        python_blocks += file_python_blocks
        external_links += file_external_links

    if problems:
        for problem in problems:
            print(problem.render())
        print(f"FAILED: {len(problems)} problem(s) across {len(files)} Markdown files")
        return 1

    print(
        f"OK: {len(files)} Markdown files, {python_blocks} Python fences, "
        f"{external_links} external source links"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
