"""Tests for _route_utils shared utilities."""

from pathlib import Path
import tempfile
import json

import pytest

from jcodemunch_mcp.parser.context._route_utils import (
    has_dependency,
    read_package_json,
    make_route_file_context,
    ENTRY_POINT_DECORATOR_RE,
)


class TestHasDependency:
    """Tests for has_dependency function."""

    def test_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\nfastapi\nrequests\n")
        assert has_dependency(tmp_path, "flask", ["requirements.txt"]) is True
        assert has_dependency(tmp_path, "fastapi", ["requirements.txt"]) is True
        assert has_dependency(tmp_path, "django", ["requirements.txt"]) is False

    def test_requirements_txt_with_version(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask==2.0.1\nfastapi>=0.100.0\nrequests~=2.28.0\n")
        assert has_dependency(tmp_path, "flask", ["requirements.txt"]) is True
        assert has_dependency(tmp_path, "requests", ["requirements.txt"]) is True

    def test_pyproject_toml_project_dependencies(self, tmp_path: Path):
        pyproject_content = """
[project]
dependencies = ["flask", "fastapi", "django>=4.0"]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject_content)
        assert has_dependency(tmp_path, "flask", ["pyproject.toml"]) is True
        assert has_dependency(tmp_path, "django", ["pyproject.toml"]) is True
        assert has_dependency(tmp_path, "rails", ["pyproject.toml"]) is False

    def test_pyproject_toml_with_extras(self, tmp_path: Path):
        pyproject_content = """
[project]
dependencies = ["flask[async]"]

[project.optional-dependencies]
dev = ["pytest"]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject_content)
        assert has_dependency(tmp_path, "flask", ["pyproject.toml"]) is True

    def test_package_json_dependencies(self, tmp_path: Path):
        pkg = {
            "dependencies": {"express": "^4.18.0", "fastify": "^4.0.0"},
            "devDependencies": {"typescript": "^5.0.0"}
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert has_dependency(tmp_path, "express", ["package.json"]) is True
        assert has_dependency(tmp_path, "fastify", ["package.json"]) is True
        assert has_dependency(tmp_path, "koa", ["package.json"]) is False

    def test_multiple_manifests(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        pyproject_content = """
[project]
dependencies = ["django"]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject_content)
        assert has_dependency(tmp_path, "flask", ["requirements.txt", "pyproject.toml"]) is True
        assert has_dependency(tmp_path, "django", ["requirements.txt", "pyproject.toml"]) is True
        assert has_dependency(tmp_path, "fastapi", ["requirements.txt", "pyproject.toml"]) is False

    def test_missing_manifest(self, tmp_path: Path):
        assert has_dependency(tmp_path, "flask", ["requirements.txt"]) is False

    def test_build_gradle(self, tmp_path: Path):
        (tmp_path / "build.gradle").write_text(
            "implementation 'org.springframework.boot:spring-boot-starter-web:3.0.0'\n"
            "implementation 'org.springframework.boot:spring-boot-starter-data-jpa:3.0.0'\n"
        )
        assert has_dependency(tmp_path, "spring-boot-starter-web", ["build.gradle"]) is True
        assert has_dependency(tmp_path, "spring-boot", ["build.gradle"]) is True

    def test_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text(
            "module example.com/myapp\n\n"
            "require (\n"
            "\tgithub.com/gin-gonic/gin v1.9.0\n"
            "\tgithub.com/go-chi/chi v1.5.4\n"
            ")\n"
        )
        assert has_dependency(tmp_path, "github.com/gin-gonic/gin", ["go.mod"]) is True
        assert has_dependency(tmp_path, "github.com/go-chi/chi", ["go.mod"]) is True
        assert has_dependency(tmp_path, "github.com/labstack/echo", ["go.mod"]) is False

    def test_gemfile(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text(
            "source 'https://rubygems.org'\n\n"
            "gem 'rails', '~> 7.0'\n"
            "gem 'puma'\n"
        )
        assert has_dependency(tmp_path, "rails", ["Gemfile"]) is True
        assert has_dependency(tmp_path, "puma", ["Gemfile"]) is True
        assert has_dependency(tmp_path, "sinatra", ["Gemfile"]) is False

    def test_mix_exs(self, tmp_path: Path):
        (tmp_path / "mix.exs").write_text(
            "defmodule MyApp.MixProject do\n"
            "  def deps do\n"
            "    [\n"
            "      {:phoenix, \"~> 1.7.0\"},\n"
            "      {:plug, \"~> 1.14\"},\n"
            "    ]\n"
            "  end\n"
            "end\n"
        )
        assert has_dependency(tmp_path, "phoenix", ["mix.exs"]) is True
        assert has_dependency(tmp_path, "plug", ["mix.exs"]) is True


class TestReadPackageJson:
    """Tests for read_package_json function."""

    def test_valid_package_json(self, tmp_path: Path):
        pkg = {"name": "my-app", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = read_package_json(tmp_path)
        assert result["name"] == "my-app"
        assert result["dependencies"]["express"] == "^4.0.0"

    def test_invalid_json(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("not valid json {")
        result = read_package_json(tmp_path)
        assert result == {}

    def test_missing_file(self, tmp_path: Path):
        result = read_package_json(tmp_path)
        assert result == {}


class TestMakeRouteFileContext:
    """Tests for make_route_file_context function."""

    def test_basic_route_context(self):
        routes = [
            {"verb": "GET", "path": "/users"},
            {"verb": "POST", "path": "/users"},
            {"verb": "GET", "path": "/users/{id}"},
        ]
        ctx = make_route_file_context("fastapi", routes)

        assert "GET /users" in ctx.description
        assert "POST /users" in ctx.description
        assert "fastapi-route" in ctx.tags
        assert "endpoint" in ctx.tags
        assert "http" in ctx.tags
        assert ctx.properties["framework"] == "fastapi"
        assert "GET" in ctx.properties["http_methods"]
        assert "POST" in ctx.properties["http_methods"]

    def test_flask_route_context(self):
        routes = [
            {"verb": "GET", "path": "/"},
            {"verb": "POST", "path": "/submit"},
        ]
        ctx = make_route_file_context("flask", routes)

        assert "flask-route" in ctx.tags
        assert ctx.properties["framework"] == "flask"

    def test_nestjs_route_context(self):
        routes = [
            {"verb": "GET", "path": "/users"},
            {"verb": "GET", "path": "/users/:id"},
            {"verb": "POST", "path": "/users"},
        ]
        ctx = make_route_file_context("nestjs", routes)

        assert "nestjs-route" in ctx.tags
        assert ctx.properties["framework"] == "nestjs"

    def test_empty_routes(self):
        ctx = make_route_file_context("flask", [])
        assert ctx.description == ""
        assert "flask-route" in ctx.tags

    def test_custom_kind(self):
        routes = [{"verb": "GET", "path": "/health"}]
        ctx = make_route_file_context("express", routes, kind="middleware")
        assert "express-middleware" in ctx.tags
        assert "endpoint" in ctx.tags


class TestEntryPointDecoratorRe:
    """Tests for the ENTRY_POINT_DECORATOR_RE regex."""

    def test_flask_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@app.route('/')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@app.get('/')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@app.post('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@blueprint.route('/api')") is not None

    def test_fastapi_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@router.get('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@router.post('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@app.get('/health')") is not None

    def test_nestjs_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@Get('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@Post('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@Controller('/api')") is not None

    def test_spring_boot_annotations(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@GetMapping('/users')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@PostMapping('/submit')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@RequestMapping('/api')") is not None

    def test_aspnet_attributes(self):
        assert ENTRY_POINT_DECORATOR_RE.search("[HttpGet]") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("[HttpPost]") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("[Route('/api')]") is not None

    def test_celery_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@celery.task") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@task") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@dramatiq.actor") is not None

    def test_pytest_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@pytest.fixture") is not None

    def test_cli_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@cli.command") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@app.command") is not None

    def test_event_decorators(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@event_handler") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@on_event") is not None

    def test_no_match_on_unrelated(self):
        assert ENTRY_POINT_DECORATOR_RE.search("def my_function():") is None
        assert ENTRY_POINT_DECORATOR_RE.search("class MyClass:") is None
        assert ENTRY_POINT_DECORATOR_RE.search("@staticmethod") is None
        assert ENTRY_POINT_DECORATOR_RE.search("@property") is None

    def test_case_insensitive(self):
        assert ENTRY_POINT_DECORATOR_RE.search("@APP.ROUTE('/')") is not None
        assert ENTRY_POINT_DECORATOR_RE.search("@Router.GET('/users')") is not None
