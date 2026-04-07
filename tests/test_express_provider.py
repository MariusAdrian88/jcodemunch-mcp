"""Tests for express.py provider (Express, Fastify, Hono, Koa)."""

from pathlib import Path
import json

import pytest

from jcodemunch_mcp.parser.context.express import ExpressProvider


class TestExpressDetection:
    """Tests for Express detection."""

    def test_express_detect(self, tmp_path: Path):
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True

    def test_fastify_detect(self, tmp_path: Path):
        pkg = {"dependencies": {"fastify": "^4.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True

    def test_hono_detect(self, tmp_path: Path):
        pkg = {"dependencies": {"hono": "^3.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True

    def test_koa_detect(self, tmp_path: Path):
        pkg = {"dependencies": {"koa": "^2.14.0", "@koa/router": "^12.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True

    def test_no_match(self, tmp_path: Path):
        pkg = {"dependencies": {"lodash": "^4.17.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is False


class TestExpressRouteExtraction:
    """Tests for Express route extraction."""

    def test_basic_routes(self, tmp_path: Path):
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        app_js = """
const express = require('express');
const app = express();

app.get('/users', (req, res) => {
    res.json([]);
});

app.post('/users', (req, res) => {
    res.status(201).json({ id: 1 });
});

app.get('/users/:id', (req, res) => {
    res.json({ id: req.params.id });
});

app.listen(3000);
"""
        (tmp_path / "app.js").write_text(app_js)
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("app.js")
        assert ctx is not None
        assert "express-route" in ctx.tags
        assert ctx.properties["framework"] == "express"
        assert "GET /users" in ctx.properties["routes"]
        assert "POST /users" in ctx.properties["routes"]
        assert "GET /users/:id" in ctx.properties["routes"]


class TestExpressMiddleware:
    """Tests for Express middleware detection."""

    def test_middleware_extraction(self, tmp_path: Path):
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        app_js = """
const express = require('express');
const app = express();

app.use(cors());
app.use('/api', authMiddleware);
app.use(Logger);

app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
});
"""
        (tmp_path / "app.js").write_text(app_js)
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("app.js")
        assert ctx is not None
        assert "express-middleware" in ctx.tags or "express-route" in ctx.tags


class TestExpressRouterMount:
    """Tests for Express router mounting."""

    def test_router_mount(self, tmp_path: Path):
        pkg = {"dependencies": {"express": "^4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        app_js = """
const express = require('express');
const app = express();
const usersRouter = require('./routes/users');

app.use('/api/users', usersRouter);
"""
        (tmp_path / "app.js").write_text(app_js)
        (tmp_path / "routes").mkdir()
        (tmp_path / "routes" / "users.js").write_text("module.exports = express.Router();")
        provider = ExpressProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        # Verify routes are extracted
        ctx = provider.get_file_context("app.js")
        assert ctx is not None
        # The app.use('/api/users', ...) should be detected as middleware/endpoint
        assert "express" in ctx.tags[0] or ctx.properties.get("framework")
