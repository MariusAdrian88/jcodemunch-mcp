"""Tests for the SQLite WAL storage backend."""

import sqlite3
import shutil
from pathlib import Path

from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore
from jcodemunch_mcp.parser.symbols import Symbol


def _make_symbol(name: str, file: str = "main.py", kind: str = "function") -> Symbol:
    """Helper to create a test symbol."""
    return Symbol(
        id=f"{file}::{name}#{kind}",
        file=file,
        name=name,
        qualified_name=name,
        kind=kind,
        language="python",
        signature=f"def {name}()",
        line=1,
        end_line=3,
        byte_offset=0,
        byte_length=20,
    )


def test_connect_creates_schema(tmp_path):
    """_connect creates tables and sets WAL pragmas."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    db_path = tmp_path / "test.db"
    conn = store._connect(db_path)

    # Check WAL mode
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"

    # Check tables exist
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert tables >= {"meta", "symbols", "files"}

    conn.close()


def test_repo_slug(tmp_path):
    """_repo_slug produces a safe filesystem slug."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    slug = store._repo_slug("local", "my-project-abc123")
    assert "/" not in slug
    assert "\\" not in slug
    assert ".." not in slug


def test_db_path(tmp_path):
    """_db_path returns {base_path}/{slug}.db."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    path = store._db_path("local", "test-abc123")
    assert path.suffix == ".db"
    assert path.parent == tmp_path


def test_save_and_load_index(tmp_path):
    """Full save → load round-trip preserves all data."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    sym = _make_symbol("greet")

    index = store.save_index(
        owner="local",
        name="test-abc123",
        source_files=["main.py"],
        symbols=[sym],
        raw_files={"main.py": "def greet(): pass"},
        file_hashes={"main.py": "abc123"},
        git_head="deadbeef",
        file_summaries={"main.py": "Entry point"},
        source_root="/tmp/proj",
        file_languages={"main.py": "python"},
        display_name="test",
        imports={"main.py": [{"specifier": "os", "names": ["path"]}]},
        file_mtimes={"main.py": 1234567890000000000},
    )

    assert index is not None
    assert index.repo == "local/test-abc123"
    assert len(index.symbols) == 1

    # Load it back
    loaded = store.load_index("local", "test-abc123")
    assert loaded is not None
    assert loaded.repo == "local/test-abc123"
    assert len(loaded.symbols) == 1
    assert loaded.symbols[0]["name"] == "greet"
    assert loaded.file_hashes == {"main.py": "abc123"}
    assert loaded.git_head == "deadbeef"
    assert loaded.file_summaries == {"main.py": "Entry point"}
    assert loaded.source_root == "/tmp/proj"
    assert loaded.display_name == "test"
    assert loaded.file_mtimes == {"main.py": 1234567890000000000}
    assert loaded.imports == {"main.py": [{"specifier": "os", "names": ["path"]}]}


def test_incremental_save(tmp_path):
    """Incremental save adds/removes symbols correctly."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    sym1 = _make_symbol("greet", "main.py")
    sym2 = _make_symbol("helper", "utils.py")

    # Full save with 2 files
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["main.py", "utils.py"],
        symbols=[sym1, sym2],
        raw_files={"main.py": "def greet(): pass", "utils.py": "def helper(): pass"},
        file_hashes={"main.py": "h1", "utils.py": "h2"},
        file_mtimes={"main.py": 100, "utils.py": 200},
    )

    # Incremental: change main.py, delete utils.py
    new_sym = _make_symbol("greet_v2", "main.py")
    updated = store.incremental_save(
        owner="local", name="test-abc123",
        changed_files=["main.py"],
        new_files=[],
        deleted_files=["utils.py"],
        new_symbols=[new_sym],
        raw_files={"main.py": "def greet_v2(): pass"},
        file_hashes={"main.py": "h1_new"},
        file_mtimes={"main.py": 300},
    )

    assert updated is not None
    assert len(updated.symbols) == 1
    assert updated.symbols[0]["name"] == "greet_v2"
    assert "utils.py" not in updated.file_hashes
    assert updated.file_hashes["main.py"] == "h1_new"


def test_detect_changes_with_mtimes(tmp_path):
    """Detects changed, new, and deleted files by mtime + hash."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["a.py", "b.py"],
        symbols=[_make_symbol("f", "a.py"), _make_symbol("g", "b.py")],
        raw_files={"a.py": "x", "b.py": "y"},
        file_hashes={"a.py": "ha", "b.py": "hb"},
        file_mtimes={"a.py": 100, "b.py": 200},
    )

    # a.py: same mtime (unchanged), b.py: different mtime + different hash (changed), c.py: new
    changed, new, deleted, hashes, mtimes = store.detect_changes_with_mtimes(
        "local", "test-abc123",
        current_mtimes={"a.py": 100, "b.py": 999, "c.py": 300},
        hash_fn=lambda fp: {"b.py": "hb_new", "c.py": "hc"}.get(fp, ""),
    )
    assert changed == ["b.py"]
    assert new == ["c.py"]
    assert deleted == []


def test_delete_index(tmp_path):
    """delete_index removes .db and content dir."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["a.py"], symbols=[], raw_files={"a.py": "x"},
    )
    assert store.has_index("local", "test-abc123")
    assert store.delete_index("local", "test-abc123")
    assert not store.has_index("local", "test-abc123")


def test_delete_and_recreate_same_process(tmp_path):
    """delete_index clears _initialized_dbs so a recreate succeeds in the same process.

    Without the discard, _connect skips the table_info check and the second save
    fails with 'no such table' because the fresh DB was never schema-initialised.
    """
    store = SQLiteIndexStore(base_path=str(tmp_path))

    store.save_index(
        owner="local", name="test-abc123",
        source_files=["a.py"], symbols=[], raw_files={"a.py": "x"},
    )
    assert store.has_index("local", "test-abc123")

    store.delete_index("local", "test-abc123")
    assert not store.has_index("local", "test-abc123")

    # Recreating the same repo must succeed — this would raise
    # sqlite3.OperationalError: no such table: symbols
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["b.py"], symbols=[], raw_files={"b.py": "y"},
    )
    assert store.has_index("local", "test-abc123")

    index = store.load_index("local", "test-abc123")
    assert index is not None
    assert index.source_files == ["b.py"]


def test_list_repos(tmp_path):
    """list_repos finds all indexed repos."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="proj-a",
        source_files=["a.py"], symbols=[_make_symbol("f")],
        raw_files={"a.py": "x"}, display_name="Project A",
    )
    repos = store.list_repos()
    assert len(repos) >= 1
    assert any(r["repo"] == "local/proj-a" for r in repos)


def test_get_symbol_content(tmp_path):
    """get_symbol_content reads by byte offset from content cache."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    content = "def greet():\n    print('hello')\n"
    sym = Symbol(
        id="main.py::greet#function", file="main.py", name="greet",
        qualified_name="greet", kind="function", language="python",
        signature="def greet()", line=1, end_line=2,
        byte_offset=0, byte_length=len(content.encode("utf-8")),
    )
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["main.py"], symbols=[sym],
        raw_files={"main.py": content},
    )
    result = store.get_symbol_content("local", "test-abc123", "main.py::greet#function")
    assert result == content


def test_get_file_content(tmp_path):
    """get_file_content reads full file from content cache."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    content = "def greet(): pass\n"
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["main.py"], symbols=[_make_symbol("greet")],
        raw_files={"main.py": content},
    )
    result = store.get_file_content("local", "test-abc123", "main.py")
    assert result == content


def test_has_index_false_before_save(tmp_path):
    """has_index returns False when no index exists."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    assert not store.has_index("local", "nonexistent-abc123")


def test_detect_changes_from_hashes(tmp_path):
    """Detects changes using precomputed hashes."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["a.py", "b.py"],
        symbols=[], raw_files={"a.py": "x", "b.py": "y"},
        file_hashes={"a.py": "ha", "b.py": "hb"},
    )
    changed, new, deleted = store.detect_changes_from_hashes(
        "local", "test-abc123",
        current_hashes={"a.py": "ha", "b.py": "hb_new", "c.py": "hc"},
    )
    assert changed == ["b.py"]
    assert new == ["c.py"]
    assert deleted == []


def test_get_symbol_by_id(tmp_path):
    """get_symbol_by_id returns one symbol without loading full index."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["main.py"],
        symbols=[_make_symbol("greet"), _make_symbol("farewell")],
        raw_files={"main.py": "x"},
    )
    sym = store.get_symbol_by_id("local", "test-abc123", "main.py::greet#function")
    assert sym is not None
    assert sym["name"] == "greet"

    missing = store.get_symbol_by_id("local", "test-abc123", "main.py::nonexistent#function")
    assert missing is None


def test_has_file(tmp_path):
    """has_file checks file existence without loading full index."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["main.py"], symbols=[], raw_files={"main.py": "x"},
    )
    assert store.has_file("local", "test-abc123", "main.py")
    assert not store.has_file("local", "test-abc123", "missing.py")


def test_get_file_languages(tmp_path):
    """get_file_languages returns path→language without loading full index."""
    store = SQLiteIndexStore(base_path=str(tmp_path))
    store.save_index(
        owner="local", name="test-abc123",
        source_files=["a.py", "b.js"], symbols=[],
        raw_files={"a.py": "x", "b.js": "y"},
        file_languages={"a.py": "python", "b.js": "javascript"},
    )
    fl = store.get_file_languages("local", "test-abc123")
    assert fl == {"a.py": "python", "b.js": "javascript"}

