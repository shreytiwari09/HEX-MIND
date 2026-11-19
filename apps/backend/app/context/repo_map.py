"""A ranked map of a project for a worker's prompt (PRD §8.4 step 3): the files that matter most
for the feature, each with the names it defines, in about 1k tokens.

Symbols are found with plain patterns (JS/TS and Python), with no parser dependency, so the map
is cheap, deterministic and safe on any project: it lists paths and identifiers only, never file
contents, and skips secret files, ignored folders and the mission's own `.hex/` files.

Ranking: files the feature names (and files changed by earlier work) come first, then the files
they import, then the files the rest of the project imports most; tests rank last.
"""

import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.context import workspace_scan as scan

DEFAULT_BUDGET_CHARS = 4000  # about 1k tokens
MAX_SYMBOLS_PER_FILE = 8
MAX_FILES_SCANNED = 800
_JS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_PY = {".py"}
_SKIP_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "go.sum",
}

_JS_DECL = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?"
    r"(?:function\s*\*?\s*|class\s+|const\s+|let\s+|var\s+|interface\s+|type\s+|enum\s+)"
    r"([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_JS_EXPORTS = re.compile(r"module\.exports\s*=\s*\{([^}]*)\}")
_JS_IMPORT = re.compile(
    r"""(?:import\s[^'"]*?from\s*|import\s*|require\(\s*|export\s[^'"]*?from\s*)['"]([^'"]+)['"]"""
)
_PY_DECL = re.compile(r"^(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)


@dataclass
class _File:
    path: str
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # resolved to project paths


def _is_test(path: str) -> bool:
    name = posixpath.basename(path)
    return bool(
        re.search(r"(^|[._-])(test|spec)([._-]|$)", name)
        or name.startswith("test_")
        or "/tests/" in f"/{path}"
        or "/__tests__/" in f"/{path}"
    )


def _symbols(path: str, text: str) -> list[str]:
    suffix = posixpath.splitext(path)[1]
    found: list[str] = []
    if suffix in _JS:
        found = _JS_DECL.findall(text)
        for block in _JS_EXPORTS.findall(text):
            found += [part.split(":")[0].strip() for part in block.split(",")]
    elif suffix in _PY:
        found = [n for n in _PY_DECL.findall(text) if not n.startswith("_")]
    unique = list(dict.fromkeys(n for n in found if n))
    return unique[:MAX_SYMBOLS_PER_FILE]


def _resolve(importer: str, spec: str, known: set[str]) -> str | None:
    """A relative JS import (`./todos`, `../lib/a.js`) to a project path, if it exists."""
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
    for candidate in (
        base,
        *(base + ext for ext in sorted(_JS)),
        *(f"{base}/index{ext}" for ext in sorted(_JS)),
    ):
        if candidate in known:
            return candidate
    return None


def _python_module_paths(files: set[str]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for path in files:
        if path.endswith(".py"):
            name = path[:-3].replace("/", ".")
            modules[name.removesuffix(".__init__")] = path
    return modules


def _scan(root: Path, paths: list[str]) -> dict[str, _File]:
    known = set(paths)
    py_modules = _python_module_paths(known)
    files: dict[str, _File] = {}
    for path in paths:
        suffix = posixpath.splitext(path)[1]
        entry = _File(path)
        if suffix in _JS | _PY:
            text = scan.read_text(root, path)
            if text is not None:
                entry.symbols = _symbols(path, text)
                if suffix in _JS:
                    for spec in _JS_IMPORT.findall(text):
                        if (target := _resolve(path, spec, known)) and target != path:
                            entry.imports.append(target)
                else:
                    for left, right in _PY_IMPORT.findall(text):
                        module = left or right
                        while module and module not in py_modules:
                            module = module.rpartition(".")[0]
                        if module and py_modules[module] != path:
                            entry.imports.append(py_modules[module])
        files[path] = entry
    return files


def rank(files: dict[str, _File], focus: list[str]) -> list[str]:
    """Paths, most relevant first. `focus` are the files the feature names or earlier work
    changed."""
    focused = {f for f in focus if f in files}
    imported_by_focus = {t for f in focused for t in files[f].imports}
    in_degree: dict[str, int] = defaultdict(int)
    for entry in files.values():
        for target in set(entry.imports):
            in_degree[target] += 1

    def score(path: str) -> int:
        value = in_degree[path] * 5
        if path in focused:
            value += 100
        if path in imported_by_focus:
            value += 30
        if files[path].symbols:
            value += 2
        if _is_test(path):
            value -= 50
        return value

    return sorted(files, key=lambda p: (-score(p), p))


def build_repo_map(
    root: Path, focus: list[str] | None = None, *, budget_chars: int = DEFAULT_BUDGET_CHARS
) -> str:
    """The map as text, or "" for an empty project. Never longer than `budget_chars` plus a
    one-line note of how many files were left out."""
    paths = [
        f.path
        for f in scan.list_files(root, max_files=MAX_FILES_SCANNED)
        if not f.path.startswith(".hex/")
        and posixpath.basename(f.path) not in _SKIP_NAMES
        and f.size <= scan.MAX_TEXT_FILE_BYTES
    ]
    if not paths:
        return ""
    files = _scan(root, paths)
    lines: list[str] = []
    used = 0
    listed = 0
    for path in rank(files, focus or []):
        entry = files[path]
        line = path + (f"  ({', '.join(entry.symbols)})" if entry.symbols else "")
        if used + len(line) + 1 > budget_chars and listed > 0:
            break
        lines.append(line)
        used += len(line) + 1
        listed += 1
    if listed < len(paths):
        lines.append(f"… and {len(paths) - listed} more files (use list_files)")
    return "\n".join(lines)
