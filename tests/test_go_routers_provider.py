"""Tests for go_routers.py provider (Gin, Chi, Echo, Fiber)."""

from pathlib import Path

import pytest

from jcodemunch_mcp.parser.context.go_routers import GoRoutersProvider


class TestGoRouterDetection:
    """Tests for Go router detection."""

    def test_gin_detect(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/gin-gonic/gin v1.9.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True

    def test_chi_detect(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/go-chi/chi v1.5.4
"""
        (tmp_path / "go.mod").write_text(go_mod)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True

    def test_echo_detect(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/labstack/echo v4.9.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True

    def test_fiber_detect(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/gofiber/fiber/v2 v2.42.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True

    def test_no_match(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/pkg/errors v0.9.1
"""
        (tmp_path / "go.mod").write_text(go_mod)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is False


class TestGoRouterRouteExtraction:
    """Tests for Go router route extraction."""

    def test_gin_routes(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/gin-gonic/gin v1.9.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        main_go = """
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    
    r.GET("/users", getUsers)
    r.POST("/users", createUser)
    r.GET("/users/:id", getUser)
    
    r.Run()
}
"""
        (tmp_path / "main.go").write_text(main_go)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("main.go")
        assert ctx is not None
        assert "gin-route" in ctx.tags
        assert ctx.properties["framework"] == "gin"
        assert "GET /users" in ctx.properties["routes"]
        assert "POST /users" in ctx.properties["routes"]
        assert "GET /users/:id" in ctx.properties["routes"]


class TestGoRouterMiddleware:
    """Tests for Go middleware detection."""

    def test_gin_middleware(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/gin-gonic/gin v1.9.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        main_go = """
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.New()
    
    r.Use(Logger())
    r.Use(Recovery())
    r.Use(AuthMiddleware())
    
    r.GET("/health", func(c *gin.Context) {
        c.JSON(200, gin.H{"status": "ok"})
    })
}
"""
        (tmp_path / "main.go").write_text(main_go)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("main.go")
        assert ctx is not None
        assert "gin-middleware" in ctx.tags or "gin-route" in ctx.tags


class TestGoRouterGroups:
    """Tests for Go router group detection."""

    def test_gin_group(self, tmp_path: Path):
        go_mod = """module example.com/myapp

require github.com/gin-gonic/gin v1.9.0
"""
        (tmp_path / "go.mod").write_text(go_mod)
        main_go = """
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    
    api := r.Group("/api")
    api.Use(AuthMiddleware())
    {
        api.GET("/users", getUsers)
        api.POST("/users", createUser)
    }
}
"""
        (tmp_path / "main.go").write_text(main_go)
        provider = GoRoutersProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("main.go")
        assert ctx is not None
        assert "gin-route" in ctx.tags
