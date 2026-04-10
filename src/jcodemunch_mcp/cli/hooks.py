"""Claude Code hook handlers for jCodemunch enforcement.

PreToolUse  — intercept Read on large code files, suggest jCodemunch tools.
PostToolUse — auto-reindex after Edit/Write to keep the index fresh.

Both read JSON from stdin and write JSON to stdout per the Claude Code
hooks specification.
"""

import json
import os
import subprocess
import sys


# Extensions that benefit from jCodemunch structural navigation.
# Kept intentionally broad — mirrors languages.py LANGUAGE_REGISTRY.
_CODE_EXTENSIONS: set[str] = {
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go",
    ".rs",
    ".java",
    ".php",
    ".rb",
    ".cs", ".cshtml", ".razor",
    ".cpp", ".c", ".h", ".hpp", ".cc", ".cxx",
    ".swift",
    ".kt", ".kts",
    ".scala",
    ".dart",
    ".lua", ".luau",
    ".ex", ".exs",
    ".erl", ".hrl",
    ".vue", ".svelte",
    ".sql",
    ".gd",       # GDScript
    ".al",       # AL (Business Central)
    ".gleam",
    ".nix",
    ".hcl", ".tf",
    ".proto",
    ".graphql", ".gql",
    ".verse",
    ".jl",       # Julia
    ".r", ".R",
    ".hs",       # Haskell
    ".f90", ".f95", ".f03", ".f08",  # Fortran
    ".groovy",
    ".pl", ".pm",  # Perl
    ".bash", ".sh", ".zsh",
}

# Minimum file size to trigger jCodemunch suggestion.
# Override with JCODEMUNCH_HOOK_MIN_SIZE env var.
_MIN_SIZE_BYTES = int(os.environ.get("JCODEMUNCH_HOOK_MIN_SIZE", "4096"))


def run_pretooluse() -> int:
    """PreToolUse hook: intercept Read calls on large code files.

    Reads hook JSON from stdin.  If the target is a code file above the
    size threshold, returns a ``deny`` decision with a message directing
    Claude to use jCodemunch tools instead.

    Small files, non-code files, and unreadable paths are silently allowed.

    Returns exit code (always 0 — errors are swallowed to avoid blocking).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Unparseable → allow

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    # Check extension
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in _CODE_EXTENSIONS:
        return 0  # Not a code file → allow

    # Check size
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return 0  # Can't stat → allow (file may not exist yet)

    if size < _MIN_SIZE_BYTES:
        return 0  # Small file → allow

    # Targeted reads (offset/limit set) are likely pre-edit — allow silently.
    tool_input = data.get("tool_input", {})
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return 0

    # Full-file exploratory read on a large code file — warn but allow.
    # Hard deny breaks the Edit workflow (Claude Code requires Read before Edit).
    # Stderr text is surfaced to the agent as guidance.
    print(
        f"jCodemunch hint: this is a {size:,}-byte code file. "
        "Prefer get_file_outline + get_symbol_source for exploration. "
        "Use Read only when you need exact line numbers for Edit.",
        file=sys.stderr,
    )
    return 0


def run_posttooluse() -> int:
    """PostToolUse hook: auto-index files after Edit/Write.

    Reads hook JSON from stdin, extracts the file path, and spawns
    ``jcodemunch-mcp index-file <path>`` as a fire-and-forget background
    process to keep the index fresh.

    Non-code files are skipped.  Errors are swallowed silently.

    Returns exit code (always 0).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    # Only re-index code files
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in _CODE_EXTENSIONS:
        return 0

    # Fire-and-forget: spawn index-file in background
    try:
        kwargs: dict = dict(
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # On Windows, CREATE_NO_WINDOW prevents a console flash
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen(
            ["jcodemunch-mcp", "index-file", file_path],
            **kwargs,
        )
    except (OSError, FileNotFoundError):
        pass  # jcodemunch-mcp not in PATH → skip silently

    return 0


def run_precompact() -> int:
    """PreCompact hook: generate session snapshot before context compaction.

    Reads hook JSON from stdin. Builds a compact snapshot of the current
    session state and returns it as a message for context injection.

    Returns exit code (always 0 — errors are swallowed to avoid blocking).
    """
    try:
        json.load(sys.stdin)  # Validate stdin is valid JSON
    except (json.JSONDecodeError, ValueError):
        return 0

    # Build snapshot in-process (no MCP round-trip needed)
    try:
        from jcodemunch_mcp.tools.get_session_snapshot import get_session_snapshot
        snapshot_result = get_session_snapshot()
        snapshot_text = snapshot_result.get("snapshot", "")
    except Exception:
        return 0  # Snapshot failure must not block compaction

    if not snapshot_text:
        return 0

    # Enrich with structural landmarks (PageRank top-N) and recently-changed symbols
    try:
        landmarks = _build_landmark_section()
        if landmarks:
            snapshot_text += landmarks
    except Exception:
        pass  # Landmark enrichment must not block compaction

    # Return snapshot as hook output for context injection.
    # PreCompact has no hookSpecificOutput variant in Claude Code's schema,
    # so we use the top-level systemMessage field instead.
    result = {
        "systemMessage": snapshot_text,
    }
    json.dump(result, sys.stdout)
    return 0


# ---------------------------------------------------------------------------
# Landmark enrichment helpers (Gap 4A — Structural Landmarks)
# ---------------------------------------------------------------------------

def _build_landmark_section(top_n: int = 20) -> str:
    """Build a compact landmarks + recently-changed section for PreCompact.

    Queries all indexed repos visible in the session journal's edited files,
    computes PageRank to find the most structurally central symbols, and
    cross-references the journal's edit log to surface recently-changed symbols.

    Returns a markdown string to append to the snapshot, or "" if no data.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from ..storage import IndexStore
        from ..tools.pagerank import compute_pagerank
        from ..tools.session_journal import get_journal
    except Exception:
        logger.debug("landmark imports failed", exc_info=True)
        return ""

    journal = get_journal()
    context = journal.get_context(max_files=50, max_queries=0, max_edits=50)
    edited_files = [e["file"] for e in context.get("files_edited", [])]
    accessed_files = [f["file"] for f in context.get("files_accessed", [])]

    if not edited_files and not accessed_files:
        return ""

    # Load all indexed repos and find which ones contain session files
    store = IndexStore()
    repo_indices: dict[str, object] = {}
    try:
        repos = store.list_repos()
    except Exception:
        return ""

    for entry in repos:
        owner = entry.get("owner", "")
        name = entry.get("name", "")
        if not owner or not name:
            continue
        repo_id = f"{owner}/{name}"
        if repo_id in repo_indices:
            continue
        try:
            idx = store.load_index(owner, name)
            if idx and idx.source_files:
                repo_indices[repo_id] = idx
        except Exception:
            continue

    if not repo_indices:
        return ""

    parts: list[str] = []

    for repo_id, index in repo_indices.items():
        if not index.imports or not index.source_files:
            continue

        # Compute PageRank
        try:
            pr_scores, _ = compute_pagerank(
                index.imports, index.source_files,
                alias_map=getattr(index, "alias_map", None),
                psr4_map=getattr(index, "psr4_map", None),
            )
        except Exception:
            logger.debug("PageRank failed for %s", repo_id, exc_info=True)
            continue

        if not pr_scores:
            continue

        # Rank files by PageRank, then pick top symbols from those files
        top_files = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)[:top_n * 2]
        top_file_set = {f for f, _ in top_files}

        # Collect symbols from top-ranked files
        symbol_pr: list[tuple[dict, float]] = []
        for sym in index.symbols:
            f = sym.get("file", "")
            if f in top_file_set:
                symbol_pr.append((sym, pr_scores.get(f, 0.0)))

        # Sort by PageRank score, take top_n
        symbol_pr.sort(key=lambda x: x[1], reverse=True)
        landmarks = symbol_pr[:top_n]

        if landmarks:
            parts.append(f"\n\n### Structural Landmarks ({repo_id})")
            for sym, score in landmarks:
                name = sym.get("name", "?")
                kind = sym.get("kind", "")
                f = sym.get("file", "")
                line = sym.get("line", 0)
                summary = sym.get("summary", "")
                loc = f"{f}:{line}" if line else f
                desc = f" — {summary}" if summary else ""
                parts.append(f"- `{name}` ({kind}, {loc}){desc}")

        # Recently-changed symbols: cross-ref edited files with index
        session_edited = {ef for ef in edited_files}
        changed_syms: list[dict] = []
        for sym in index.symbols:
            if sym.get("file", "") in session_edited:
                changed_syms.append(sym)

        if changed_syms:
            parts.append(f"\n### Recently Changed ({repo_id})")
            # Deduplicate and limit
            seen: set[str] = set()
            count = 0
            for sym in changed_syms:
                sid = sym.get("id", sym.get("name", ""))
                if sid in seen:
                    continue
                seen.add(sid)
                name = sym.get("name", "?")
                kind = sym.get("kind", "")
                f = sym.get("file", "")
                line = sym.get("line", 0)
                parts.append(f"- `{name}` ({kind}, {f}:{line})")
                count += 1
                if count >= 20:
                    break

    return "\n".join(parts) if parts else ""
