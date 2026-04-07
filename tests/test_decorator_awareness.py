"""Integration tests for decorator awareness feature.

Tests:
1. get_file_outline surfaces decorators for decorated symbols
2. search_symbols surfaces decorators in results
3. search_symbols can filter by decorator
4. Cross-cutting concern workflow: finding endpoints that lack a decorator
"""
import pytest

from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.get_file_outline import get_file_outline
from jcodemunch_mcp.tools.search_symbols import search_symbols


@pytest.fixture
def decorator_test_repo(tmp_path):
    """Create a mini project with decorated and undecorated functions."""
    src = tmp_path / "src"
    src.mkdir()

    # Create endpoints.py with CSRF-style decorators
    (src / "endpoints.py").write_text('''
@csrf_protect
def create_user():
    """Create a new user account."""
    pass

@csrf_protect
def delete_user():
    """Delete a user account."""
    pass

def public_info():
    """Public endpoint - no auth needed."""
    pass

@route("/admin")
@csrf_protect
def admin_panel():
    """Admin panel - requires CSRF."""
    pass

def health_check():
    """Health check - no auth."""
    pass
''')

    idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=str(tmp_path / "idx"))
    return idx["repo"], str(tmp_path / "idx")


class TestDecoratorSurfaceInOutline:
    """Test that get_file_outline surfaces decorators."""

    def test_decorated_function_has_decorators_field(self, decorator_test_repo):
        """Decorated functions should have a decorators field in get_file_outline."""
        repo, storage = decorator_test_repo
        result = get_file_outline(repo=repo, file_path="src/endpoints.py", storage_path=storage)

        assert "symbols" in result
        symbols = {s["name"]: s for s in result["symbols"]}

        # create_user is decorated with @csrf_protect
        assert "create_user" in symbols
        assert "decorators" in symbols["create_user"], "Decorated function should have decorators field"
        assert "@csrf_protect" in symbols["create_user"]["decorators"]

    def test_undecorated_function_lacks_decorators_field(self, decorator_test_repo):
        """Undecorated functions should NOT have a decorators field."""
        repo, storage = decorator_test_repo
        result = get_file_outline(repo=repo, file_path="src/endpoints.py", storage_path=storage)

        symbols = {s["name"]: s for s in result["symbols"]}

        # public_info has no decorator
        assert "public_info" in symbols
        assert "decorators" not in symbols["public_info"], "Undecorated function should not have decorators field"

    def test_multiple_decorators_all_listed(self, decorator_test_repo):
        """Functions with multiple decorators should have all of them listed."""
        repo, storage = decorator_test_repo
        result = get_file_outline(repo=repo, file_path="src/endpoints.py", storage_path=storage)

        symbols = {s["name"]: s for s in result["symbols"]}

        # admin_panel has @route and @csrf_protect
        assert "admin_panel" in symbols
        assert "decorators" in symbols["admin_panel"]
        decs = symbols["admin_panel"]["decorators"]
        # Decorators include their arguments, so we check for substrings
        assert any("@route" in d for d in decs), f"Expected @route in decorators: {decs}"
        assert any("@csrf_protect" in d for d in decs), f"Expected @csrf_protect in decorators: {decs}"


class TestDecoratorSurfaceInSearch:
    """Test that search_symbols surfaces decorators in results."""

    def test_search_result_includes_decorators_for_decorated(self, decorator_test_repo):
        """search_symbols results should include decorators for decorated symbols."""
        repo, storage = decorator_test_repo

        result = search_symbols(repo=repo, query="create_user", detail_level="standard", storage_path=storage)

        assert result.get("result_count", 0) > 0
        found = result["results"][0]

        assert "decorators" in found, "Result for decorated symbol should have decorators"
        assert "@csrf_protect" in found["decorators"]

    def test_search_result_lacks_decorators_for_undecorated(self, decorator_test_repo):
        """search_symbols results should NOT include decorators for undecorated symbols."""
        repo, storage = decorator_test_repo

        result = search_symbols(repo=repo, query="public_info", detail_level="standard", storage_path=storage)

        assert result.get("result_count", 0) > 0
        found = result["results"][0]

        assert "decorators" not in found, "Result for undecorated symbol should not have decorators"


class TestDecoratorFilter:
    """Test that search_symbols can filter by decorator."""

    def test_filter_by_csrf_protect(self, decorator_test_repo):
        """search_symbols with decorator='csrf_protect' returns only protected endpoints."""
        repo, storage = decorator_test_repo

        # Use query="def" to match all Python functions (BM25 needs non-empty query)
        result = search_symbols(repo=repo, query="def", kind="function", decorator="csrf_protect",
                               detail_level="standard", storage_path=storage)

        names = {r["name"] for r in result["results"]}
        assert "create_user" in names
        assert "delete_user" in names
        assert "admin_panel" in names
        # Should NOT include undecorated functions
        assert "public_info" not in names
        assert "health_check" not in names

    def test_filter_by_route(self, decorator_test_repo):
        """search_symbols with decorator='route' returns only routed endpoints."""
        repo, storage = decorator_test_repo

        result = search_symbols(repo=repo, query="def", kind="function", decorator="route",
                               detail_level="standard", storage_path=storage)

        names = {r["name"] for r in result["results"]}
        assert "admin_panel" in names
        # Should NOT include functions without @route
        assert "create_user" not in names
        assert "public_info" not in names

    def test_filter_by_nonexistent_returns_empty(self, decorator_test_repo):
        """search_symbols with non-existent decorator returns empty with negative_evidence."""
        repo, storage = decorator_test_repo

        result = search_symbols(repo=repo, query="def", kind="function", decorator="nonexistent_decorator",
                               detail_level="standard", storage_path=storage)

        assert result.get("result_count", 0) == 0
        assert "negative_evidence" in result
        assert result["negative_evidence"]["verdict"] == "no_implementation_found"


class TestCrossCuttingConcernWorkflow:
    """Test the cross-cutting concern workflow (CSRF scenario).

    This simulates the benchmark scenario:
    1. Get all endpoint functions
    2. Get protected endpoints (with @csrf_protect)
    3. Compute set difference to find unprotected endpoints
    """

    def test_find_unprotected_endpoints(self, decorator_test_repo):
        """Find endpoints that lack CSRF protection using set difference."""
        repo, storage = decorator_test_repo

        # Step 1: Get all functions (use query="def" for BM25 scoring)
        all_funcs_result = search_symbols(repo=repo, query="def", kind="function",
                                         detail_level="compact", storage_path=storage)
        all_functions = {r["name"] for r in all_funcs_result["results"]}

        # Step 2: Get protected functions
        protected_result = search_symbols(repo=repo, query="def", kind="function",
                                         decorator="csrf_protect", detail_level="compact", storage_path=storage)
        protected_functions = {r["name"] for r in protected_result["results"]}

        # Step 3: Set difference = unprotected
        unprotected = all_functions - protected_functions

        # Verify unprotected functions are what we expect
        assert "public_info" in unprotected
        assert "health_check" in unprotected
        # Protected functions should NOT be in unprotected
        assert "create_user" not in unprotected
        assert "delete_user" not in unprotected
        assert "admin_panel" not in unprotected  # has @csrf_protect despite @route

    def test_empty_protected_set_means_all_unprotected(self, tmp_path):
        """If no functions have a decorator, all functions are unprotected."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "api.py").write_text('''
def public_endpoint():
    pass

def another_public():
    pass
''')

        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=str(tmp_path / "idx"))
        repo = idx["repo"]
        storage = str(tmp_path / "idx")

        all_funcs = search_symbols(repo=repo, query="", kind="function",
                                  detail_level="compact", storage_path=storage)
        protected = search_symbols(repo=repo, query="", kind="function",
                                  decorator="auth_required", detail_level="compact", storage_path=storage)

        all_names = {r["name"] for r in all_funcs["results"]}
        protected_names = {r["name"] for r in protected["results"]}

        # All functions should be unprotected
        assert all_names - protected_names == all_names


class TestDecoratorCaseInsensitive:
    """Test that decorator filter is case-insensitive."""

    def test_decorator_filter_case_insensitive(self, decorator_test_repo):
        """Decorator filter should match regardless of case."""
        repo, storage = decorator_test_repo

        # Try lowercase
        result_lower = search_symbols(repo=repo, query="def", kind="function", decorator="csrf",
                                     detail_level="compact", storage_path=storage)
        # Try uppercase
        result_upper = search_symbols(repo=repo, query="def", kind="function", decorator="CSRF",
                                     detail_level="compact", storage_path=storage)
        # Try mixed
        result_mixed = search_symbols(repo=repo, query="def", kind="function", decorator="Csrf",
                                     detail_level="compact", storage_path=storage)

        # All should return the same results
        names_lower = {r["name"] for r in result_lower["results"]}
        names_upper = {r["name"] for r in result_upper["results"]}
        names_mixed = {r["name"] for r in result_mixed["results"]}

        assert names_lower == names_upper == names_mixed
        assert "create_user" in names_lower
