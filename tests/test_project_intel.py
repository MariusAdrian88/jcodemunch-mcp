"""Tests for get_project_intel — auto-discovered project intelligence."""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from jcodemunch_mcp.tools.get_project_intel import (
    _build_cross_references,
    _discover_intel_files,
    _extract_file_tokens,
    _fuzzy_path_match,
    _parse_circleci,
    _parse_compose,
    _parse_dockerfile,
    _parse_env_template,
    _parse_github_actions,
    _parse_gitlab_ci,
    _parse_k8s_manifest,
    _parse_makefile,
    _parse_package_scripts,
    _parse_pyproject_scripts,
    get_project_intel,
)


# ── Dockerfile parser ──────────────────────────────────────────────────

class TestParseDockerfile:
    def test_basic(self):
        content = textwrap.dedent("""\
            FROM python:3.12-slim AS builder
            WORKDIR /app
            COPY requirements.txt .
            COPY src/ /app/src/
            RUN pip install -r requirements.txt
            EXPOSE 8080
            CMD ["python", "src/server.py"]
        """)
        result = _parse_dockerfile(content, "Dockerfile")
        assert result["file"] == "Dockerfile"
        assert len(result["stages"]) == 1
        assert result["stages"][0]["image"] == "python:3.12-slim"
        assert result["stages"][0]["alias"] == "builder"
        assert "8080" in result["ports"]
        assert result["entrypoint"] == "python src/server.py"
        assert "src/" in result["copy_sources"]
        assert result["workdir"] == "/app"

    def test_multistage(self):
        content = textwrap.dedent("""\
            FROM node:18 AS build
            RUN npm ci
            FROM nginx:alpine
            COPY --from=build /app/dist /usr/share/nginx/html
            EXPOSE 80
        """)
        result = _parse_dockerfile(content, "Dockerfile")
        assert len(result["stages"]) == 2
        assert result["stages"][1]["image"] == "nginx:alpine"

    def test_env_and_arg(self):
        content = textwrap.dedent("""\
            FROM ubuntu:22.04
            ARG VERSION=1.0
            ENV NODE_ENV=production
            ENV PORT=3000
        """)
        result = _parse_dockerfile(content, "Dockerfile")
        assert "VERSION" in result["args"]
        assert "NODE_ENV" in result["env_vars"]
        assert "PORT" in result["env_vars"]

    def test_shell_form_cmd(self):
        content = "FROM alpine\nCMD python main.py\n"
        result = _parse_dockerfile(content, "Dockerfile")
        assert result["entrypoint"] == "python main.py"

    def test_empty(self):
        result = _parse_dockerfile("", "Dockerfile")
        assert result["stages"] == []
        assert result["entrypoint"] is None


# ── docker-compose parser ──────────────────────────────────────────────

class TestParseCompose:
    COMPOSE_YAML = textwrap.dedent("""\
        services:
          api:
            build: ./api
            ports:
              - "8080:8080"
            environment:
              - DATABASE_URL=postgres://db:5432
            depends_on:
              - db
          db:
            image: postgres:16
            ports:
              - "5432:5432"
    """)

    def test_yaml_parse(self):
        result = _parse_compose(self.COMPOSE_YAML, "docker-compose.yml")
        assert len(result) == 2
        api = next(s for s in result if s["name"] == "api")
        assert api["build_context"] == "./api"
        assert "8080:8080" in api["ports"]
        assert "DATABASE_URL" in api["env_vars"]
        assert "db" in api["depends_on"]

        db = next(s for s in result if s["name"] == "db")
        assert db["image"] == "postgres:16"

    def test_regex_fallback(self):
        with patch("jcodemunch_mcp.tools.get_project_intel._load_yaml", return_value=None):
            result = _parse_compose(self.COMPOSE_YAML, "docker-compose.yml")
        assert len(result) >= 2
        names = {s["name"] for s in result}
        assert "api" in names
        assert "db" in names

    def test_empty(self):
        result = _parse_compose("", "docker-compose.yml")
        assert result == []


# ── K8s manifest parser ─────────────────────────────────────────────

class TestParseK8s:
    K8S_YAML = textwrap.dedent("""\
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: api-server
          namespace: production
        spec:
          replicas: 3
          template:
            spec:
              containers:
                - name: api
                  image: myapp:latest
                  ports:
                    - containerPort: 8080
    """)

    def test_yaml_parse(self):
        result = _parse_k8s_manifest(self.K8S_YAML, "k8s/api.yaml")
        assert len(result) == 1
        r = result[0]
        assert r["kind"] == "Deployment"
        assert r["name"] == "api-server"
        assert r["namespace"] == "production"
        assert "myapp:latest" in r["images"]
        assert 8080 in r["ports"]
        assert r["replicas"] == 3

    def test_regex_fallback(self):
        with patch("jcodemunch_mcp.tools.get_project_intel._load_yaml_all", return_value=[]):
            result = _parse_k8s_manifest(self.K8S_YAML, "k8s/api.yaml")
        assert len(result) == 1
        assert result[0]["kind"] == "Deployment"

    def test_multi_doc(self):
        content = textwrap.dedent("""\
            apiVersion: v1
            kind: Service
            metadata:
              name: api-svc
            ---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: api-deploy
        """)
        result = _parse_k8s_manifest(content, "k8s/all.yaml")
        assert len(result) >= 1  # depends on pyyaml availability
        kinds = {r["kind"] for r in result}
        assert "Service" in kinds or "Deployment" in kinds

    def test_empty(self):
        result = _parse_k8s_manifest("", "k8s/empty.yaml")
        assert result == []


# ── GitHub Actions parser ──────────────────────────────────────────────

class TestParseGitHubActions:
    GHA_YAML = textwrap.dedent("""\
        name: CI
        on: [push, pull_request]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - run: npm test
              - run: npm run lint
          build:
            runs-on: ubuntu-latest
            needs: test
            steps:
              - run: npm run build
    """)

    def test_yaml_parse(self):
        result = _parse_github_actions(self.GHA_YAML, ".github/workflows/ci.yml")
        assert result["name"] == "CI"
        assert "push" in result["triggers"]
        assert "pull_request" in result["triggers"]
        assert len(result["jobs"]) == 2
        test_job = next(j for j in result["jobs"] if j["id"] == "test")
        assert "npm test" in test_job["run_commands"]
        assert test_job["runner"] == "ubuntu-latest"

    def test_regex_fallback(self):
        with patch("jcodemunch_mcp.tools.get_project_intel._load_yaml", return_value=None):
            result = _parse_github_actions(self.GHA_YAML, ".github/workflows/ci.yml")
        assert result["name"] == "CI"
        assert len(result["jobs"]) >= 1

    def test_empty(self):
        result = _parse_github_actions("", ".github/workflows/ci.yml")
        assert result["jobs"] == []


# ── GitLab CI parser ───────────────────────────────────────────────────

class TestParseGitLabCI:
    GITLAB_YAML = textwrap.dedent("""\
        stages:
          - build
          - test
          - deploy
        build_job:
          stage: build
          image: node:18
          script:
            - npm ci
            - npm run build
        test_job:
          stage: test
          script:
            - npm test
    """)

    def test_yaml_parse(self):
        result = _parse_gitlab_ci(self.GITLAB_YAML, ".gitlab-ci.yml")
        assert result["stages"] == ["build", "test", "deploy"]
        assert len(result["jobs"]) == 2
        build = next(j for j in result["jobs"] if j["name"] == "build_job")
        assert build["stage"] == "build"
        assert build["image"] == "node:18"
        assert "npm ci" in build["scripts"]

    def test_hidden_jobs_excluded(self):
        content = textwrap.dedent("""\
            .template:
              script: echo hi
            real_job:
              script: echo real
        """)
        result = _parse_gitlab_ci(content, ".gitlab-ci.yml")
        names = {j["name"] for j in result["jobs"]}
        assert ".template" not in names
        assert "real_job" in names


# ── CircleCI parser ────────────────────────────────────────────────────

class TestParseCircleCI:
    CIRCLE_YAML = textwrap.dedent("""\
        version: 2.1
        jobs:
          build:
            docker:
              - image: node:18
            steps:
              - checkout
              - run: npm ci
              - run:
                  command: npm test
          deploy:
            steps:
              - run: ./deploy.sh
    """)

    def test_yaml_parse(self):
        result = _parse_circleci(self.CIRCLE_YAML, ".circleci/config.yml")
        assert len(result["jobs"]) == 2
        build = next(j for j in result["jobs"] if j["name"] == "build")
        assert "npm ci" in build["scripts"]
        assert "npm test" in build["scripts"]


# ── .env template parser ──────────────────────────────────────────────

class TestParseEnvTemplate:
    def test_basic(self):
        content = textwrap.dedent("""\
            # Database connection
            DATABASE_URL=postgresql://localhost:5432/mydb
            REDIS_URL=redis://localhost:6379

            # API keys
            API_KEY=
            SECRET_KEY=changeme  # Please change this
        """)
        result = _parse_env_template(content, ".env.example")
        assert len(result) == 4
        db = next(v for v in result if v["name"] == "DATABASE_URL")
        assert db["default"] == "postgresql://localhost:5432/mydb"
        assert db["comment"] == "Database connection"

        api = next(v for v in result if v["name"] == "API_KEY")
        assert api["default"] is None

        secret = next(v for v in result if v["name"] == "SECRET_KEY")
        assert secret["default"] == "changeme"

    def test_empty(self):
        assert _parse_env_template("", ".env.example") == []

    def test_comments_only(self):
        assert _parse_env_template("# just a comment\n# another\n", ".env.example") == []


# ── package.json scripts parser ───────────────────────────────────────

class TestParsePackageScripts:
    def test_basic(self):
        content = json.dumps({
            "name": "myapp",
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "test": "jest",
                "lint": "eslint .",
            }
        })
        result = _parse_package_scripts(content, "package.json")
        assert len(result) == 4
        names = {s["name"] for s in result}
        assert names == {"dev", "build", "test", "lint"}

    def test_no_scripts(self):
        result = _parse_package_scripts('{"name": "foo"}', "package.json")
        assert result == []

    def test_invalid_json(self):
        result = _parse_package_scripts("not json", "package.json")
        assert result == []


# ── Makefile parser ───────────────────────────────────────────────────

class TestParseMakefile:
    def test_basic(self):
        content = textwrap.dedent("""\
            .PHONY: test build deploy

            test: lint
            \tpytest tests/

            build: test
            \tdocker build -t myapp .

            deploy: build
            \tkubectl apply -f k8s/

            lint:
            \truff check .
        """)
        result = _parse_makefile(content, "Makefile")
        assert len(result) == 4
        test = next(t for t in result if t["target"] == "test")
        assert "lint" in test["prerequisites"]
        assert test["recipe_hint"] == "pytest tests/"

        deploy = next(t for t in result if t["target"] == "deploy")
        assert "build" in deploy["prerequisites"]
        assert deploy["recipe_hint"] == "kubectl apply -f k8s/"

    def test_special_targets_excluded(self):
        content = ".PHONY: all\nall:\n\techo hi\n"
        result = _parse_makefile(content, "Makefile")
        targets = {t["target"] for t in result}
        assert ".PHONY" not in targets
        assert "all" in targets

    def test_empty(self):
        assert _parse_makefile("", "Makefile") == []


# ── pyproject.toml scripts parser ─────────────────────────────────────

class TestParsePyprojectScripts:
    def test_pep621(self):
        content = textwrap.dedent("""\
            [project]
            name = "myapp"

            [project.scripts]
            myapp = "myapp.cli:main"
            myapp-worker = "myapp.worker:run"
        """)
        result = _parse_pyproject_scripts(content, "pyproject.toml")
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert "myapp" in names
        assert "myapp-worker" in names

    def test_poetry(self):
        content = textwrap.dedent("""\
            [tool.poetry]
            name = "myapp"

            [tool.poetry.scripts]
            serve = "myapp.server:main"
        """)
        result = _parse_pyproject_scripts(content, "pyproject.toml")
        assert len(result) >= 1
        assert any(s["name"] == "serve" for s in result)

    def test_no_scripts(self):
        content = "[project]\nname = \"foo\"\n"
        result = _parse_pyproject_scripts(content, "pyproject.toml")
        assert result == []


# ── File discovery ─────────────────────────────────────────────────────

class TestDiscovery:
    def test_discovers_dockerfile(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["infra"]) == 1

    def test_discovers_compose(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["infra"]) == 1

    def test_discovers_github_actions(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: CI\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["ci"]) == 1

    def test_discovers_env_template(self, tmp_path):
        (tmp_path / ".env.example").write_text("FOO=bar\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["config"]) == 1

    def test_discovers_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"scripts":{"test":"jest"}}\n')
        result = _discover_intel_files(str(tmp_path))
        assert len(result["deps"]) == 1

    def test_discovers_makefile(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["deps"]) == 1

    def test_discovers_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="foo"\n')
        result = _discover_intel_files(str(tmp_path))
        assert len(result["deps"]) == 1

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"scripts":{"test":"jest"}}\n')
        result = _discover_intel_files(str(tmp_path))
        assert len(result["deps"]) == 0

    def test_discovers_k8s_dir(self, tmp_path):
        k8s = tmp_path / "k8s"
        k8s.mkdir()
        (k8s / "deployment.yaml").write_text("kind: Deployment\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["infra"]) == 1

    def test_env_file_not_discovered(self, tmp_path):
        """Actual .env should never be discovered (security)."""
        (tmp_path / ".env").write_text("SECRET=oops\n")
        result = _discover_intel_files(str(tmp_path))
        assert len(result["config"]) == 0


# ── Helpers ────────────────────────────────────────────────────────────

class TestHelpers:
    def test_extract_file_tokens(self):
        tokens = _extract_file_tokens("python src/server.py --port 8080")
        assert "src/server.py" in tokens

    def test_extract_file_tokens_no_match(self):
        tokens = _extract_file_tokens("echo hello")
        assert tokens == []

    def test_fuzzy_path_match_exact(self):
        files = {"src/server.py", "src/db.py"}
        assert _fuzzy_path_match("src/server.py", files) == "src/server.py"

    def test_fuzzy_path_match_suffix(self):
        files = {"src/server.py", "src/db.py"}
        assert _fuzzy_path_match("server.py", files) == "src/server.py"

    def test_fuzzy_path_match_no_match(self):
        files = {"src/server.py"}
        assert _fuzzy_path_match("other.py", files) is None

    def test_fuzzy_path_match_leading_dot_slash(self):
        files = {"src/main.js"}
        assert _fuzzy_path_match("./src/main.js", files) == "src/main.js"


# ── Cross-references ──────────────────────────────────────────────────

class TestCrossReferences:
    def _make_index(self, source_files, symbols=None):
        """Minimal mock index for cross-ref tests."""
        class MockIndex:
            pass
        idx = MockIndex()
        idx.source_files = source_files
        idx.symbols = symbols or []
        return idx

    def test_dockerfile_entrypoint(self):
        discoveries = {
            "infra": {
                "dockerfiles": [{
                    "file": "Dockerfile",
                    "entrypoint": "python src/server.py",
                    "copy_sources": [],
                }],
            },
        }
        index = self._make_index(["src/server.py", "src/utils.py"])
        refs = _build_cross_references(discoveries, index)
        assert any(r["type"] == "entrypoint" and r["target_file"] == "src/server.py" for r in refs)

    def test_dockerfile_copy_source(self):
        discoveries = {
            "infra": {
                "dockerfiles": [{
                    "file": "Dockerfile",
                    "entrypoint": None,
                    "copy_sources": ["src/"],
                }],
            },
        }
        index = self._make_index(["src/main.py", "src/utils.py", "tests/test_main.py"])
        refs = _build_cross_references(discoveries, index)
        copy_ref = next((r for r in refs if r["type"] == "copy_source"), None)
        assert copy_ref is not None
        assert copy_ref["matched_files"] == 2

    def test_compose_build_context(self):
        discoveries = {
            "infra": {
                "dockerfiles": [],
                "compose_services": [{
                    "name": "api",
                    "build_context": "./api",
                }],
            },
        }
        index = self._make_index(["api/main.py", "api/utils.py", "web/index.js"])
        refs = _build_cross_references(discoveries, index)
        assert any(r["type"] == "build_context" for r in refs)

    def test_env_var_keyword_match(self):
        discoveries = {
            "config": {
                "env_vars": [{"name": "DATABASE_URL"}],
            },
        }
        index = self._make_index(
            ["src/db.py"],
            symbols=[{"file": "src/db.py", "keywords": ["DATABASE_URL", "connection"]}],
        )
        refs = _build_cross_references(discoveries, index)
        assert any(r["type"] == "env_usage" and "DATABASE_URL" in r["source"] for r in refs)

    def test_ci_run_target(self):
        discoveries = {
            "ci": {
                "pipelines": [{
                    "file": ".github/workflows/ci.yml",
                    "jobs": [{
                        "name": "test",
                        "run_commands": ["pytest tests/test_main.py"],
                    }],
                }],
            },
        }
        index = self._make_index(["tests/test_main.py", "src/main.py"])
        refs = _build_cross_references(discoveries, index)
        assert any(r["type"] == "ci_target" and r["target_file"] == "tests/test_main.py" for r in refs)

    def test_empty_discoveries(self):
        index = self._make_index(["src/main.py"])
        refs = _build_cross_references({}, index)
        assert refs == []


# ── Integration: full pipeline ────────────────────────────────────────

class TestIntegration:
    """Integration tests using index_folder on tmp_path fixtures."""

    def _build_project(self, tmp_path):
        """Create a minimal project with intel files + code."""
        # Python code
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("def main():\n    print('hello')\n")
        (src / "db.py").write_text("import os\nDB_URL = os.environ.get('DATABASE_URL')\n")

        # Dockerfile
        (tmp_path / "Dockerfile").write_text(textwrap.dedent("""\
            FROM python:3.12
            COPY src/ /app/src/
            CMD ["python", "src/main.py"]
        """))

        # .env.example
        (tmp_path / ".env.example").write_text("DATABASE_URL=postgresql://localhost/mydb\nAPI_KEY=\n")

        # package.json (even in a Python project, maybe for docs tooling)
        (tmp_path / "package.json").write_text(json.dumps({
            "scripts": {"docs": "mkdocs serve"}
        }))

        # pyproject.toml
        (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
            [project]
            name = "myproject"

            [project.scripts]
            myapp = "src.main:main"
        """))

        return tmp_path

    def _index_project(self, tmp_path):
        """Index the project and return (repo_id, storage_path)."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        store = tmp_path / "store"
        store.mkdir()
        result = index_folder(str(tmp_path), use_ai_summaries=False, storage_path=str(store))
        assert result.get("success"), f"index_folder failed: {result}"
        result["storage_path"] = str(store)
        return result

    def test_full_pipeline(self, tmp_path):
        proj = self._build_project(tmp_path)
        idx_result = self._index_project(proj)
        repo = idx_result["repo"]

        result = get_project_intel(repo, storage_path=idx_result["storage_path"])
        assert "error" not in result
        assert result["file_count"] >= 3  # Dockerfile, .env.example, package.json, pyproject.toml
        assert result["category_count"] >= 1

        # Check infra
        assert "infra" in result["categories"]
        dockerfiles = result["categories"]["infra"]["dockerfiles"]
        assert len(dockerfiles) == 1
        assert dockerfiles[0]["entrypoint"] == "python src/main.py"

        # Check config
        assert "config" in result["categories"]
        env_vars = result["categories"]["config"]["env_vars"]
        assert any(v["name"] == "DATABASE_URL" for v in env_vars)

        # Check deps
        assert "deps" in result["categories"]
        scripts = result["categories"]["deps"]["scripts"]
        assert any(s["name"] == "docs" for s in scripts)
        assert any(s["name"] == "myapp" for s in scripts)

    def test_single_category_filter(self, tmp_path):
        proj = self._build_project(tmp_path)
        idx_result = self._index_project(proj)
        repo = idx_result["repo"]

        result = get_project_intel(repo, category="config", storage_path=idx_result["storage_path"])
        assert "error" not in result
        # Only config category should be present
        assert "config" in result["categories"]
        # Other filesystem categories should not be present
        assert "ci" not in result["categories"]

    def test_cross_refs_found(self, tmp_path):
        proj = self._build_project(tmp_path)
        idx_result = self._index_project(proj)
        repo = idx_result["repo"]

        result = get_project_intel(repo, storage_path=idx_result["storage_path"])
        # Should find Dockerfile ENTRYPOINT -> src/main.py
        xrefs = result.get("cross_references", [])
        entrypoint_refs = [r for r in xrefs if r["type"] == "entrypoint"]
        assert len(entrypoint_refs) >= 1

    def test_invalid_category(self, tmp_path):
        proj = self._build_project(tmp_path)
        idx_result = self._index_project(proj)
        repo = idx_result["repo"]

        result = get_project_intel(repo, category="bogus", storage_path=idx_result["storage_path"])
        assert "error" in result

    def test_nonexistent_repo(self):
        result = get_project_intel("nonexistent/repo")
        assert "error" in result


# ── Edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_project(self, tmp_path):
        """A project with no intel files returns empty categories."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        store = tmp_path / "store"
        store.mkdir()
        result = index_folder(str(tmp_path), use_ai_summaries=False, storage_path=str(store))
        assert result.get("success")

        intel = get_project_intel(result["repo"], storage_path=str(store))
        assert "error" not in intel
        assert intel["file_count"] == 0

    def test_malformed_yaml_handled(self):
        """Malformed YAML in compose file doesn't crash."""
        content = "services:\n  bad:\n  - this: is: invalid: yaml: {{{"
        result = _parse_compose(content, "docker-compose.yml")
        # Should not raise, may return empty or partial
        assert isinstance(result, list)

    def test_large_file_skipped(self, tmp_path):
        """Files over 256KB are skipped."""
        (tmp_path / "Dockerfile").write_text("FROM alpine\n" + "RUN echo x\n" * 30000)
        result = _discover_intel_files(str(tmp_path))
        # File is discovered (discovery doesn't check size), but _safe_read skips it
        from jcodemunch_mcp.tools.get_project_intel import _safe_read
        content = _safe_read(str(tmp_path / "Dockerfile"))
        # 30000 * ~12 bytes = ~360KB > 256KB limit
        assert content is None

    def test_meta_fields(self, tmp_path):
        """Result always has _meta with timing and source_root."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        store = tmp_path / "store"
        store.mkdir()
        result = index_folder(str(tmp_path), use_ai_summaries=False, storage_path=str(store))
        assert result.get("success")

        intel = get_project_intel(result["repo"], storage_path=str(store))
        assert "_meta" in intel
        assert "timing_ms" in intel["_meta"]
        assert "source_root" in intel["_meta"]


# ── Return shape validation ───────────────────────────────────────────

class TestReturnShape:
    """Verify the return dict structure for various inputs."""

    def test_all_category_keys(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")

        from jcodemunch_mcp.tools.index_folder import index_folder
        store = tmp_path / "store"
        store.mkdir()
        result = index_folder(str(tmp_path), use_ai_summaries=False, storage_path=str(store))
        assert result.get("success")

        intel = get_project_intel(result["repo"], storage_path=str(store))
        assert "repo" in intel
        assert "categories" in intel
        assert "cross_references" in intel
        assert "file_count" in intel
        assert "category_count" in intel
        assert "_meta" in intel

        # All 6 categories should be present when category="all"
        cats = intel["categories"]
        for cat in ("infra", "ci", "config", "deps", "api", "data"):
            assert cat in cats, f"Missing category: {cat}"
