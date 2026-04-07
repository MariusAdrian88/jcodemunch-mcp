"""Tests for rails.py provider."""

from pathlib import Path

import pytest

from jcodemunch_mcp.parser.context.rails import RailsProvider


class TestRailsDetection:
    """Tests for Rails detection."""

    def test_rails_detect(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n")
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        (tmp_path / "config" / "routes.rb").write_text("Rails.application.routes.draw do\nend\n")
        provider = RailsProvider()
        assert provider.detect(tmp_path) is True

    def test_no_gemfile(self, tmp_path: Path):
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        (tmp_path / "config" / "routes.rb").write_text("Rails.application.routes.draw do\nend\n")
        provider = RailsProvider()
        assert provider.detect(tmp_path) is False

    def test_no_routes_rb(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails'\n")
        provider = RailsProvider()
        assert provider.detect(tmp_path) is False

    def test_no_rails_gem(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'sinatra'\n")
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        (tmp_path / "config" / "routes.rb").write_text("Rails.application.routes.draw do\nend\n")
        provider = RailsProvider()
        assert provider.detect(tmp_path) is False


class TestRailsRouteExtraction:
    """Tests for Rails route extraction."""

    def test_resources_route(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n")
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        routes_rb = """
Rails.application.routes.draw do
  resources :users
end
"""
        (tmp_path / "config" / "routes.rb").write_text(routes_rb)
        provider = RailsProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("config/routes.rb")
        assert ctx is not None
        assert "rails-route" in ctx.tags
        assert ctx.properties["framework"] == "rails"
        # resources :users expands to standard REST routes

    def test_verb_routes(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n")
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        routes_rb = """
Rails.application.routes.draw do
  get 'health', to: 'health#index'
  post 'webhooks/github', to: 'webhooks#github'
end
"""
        (tmp_path / "config" / "routes.rb").write_text(routes_rb)
        provider = RailsProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("config/routes.rb")
        assert ctx is not None
        assert "rails-route" in ctx.tags


class TestRailsNamespace:
    """Tests for Rails namespace routes."""

    def test_namespace_routes(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n")
        (tmp_path / "config" / "routes.rb").parent.mkdir(parents=True)
        routes_rb = """
Rails.application.routes.draw do
  namespace :api do
    resources :users
  end
end
"""
        (tmp_path / "config" / "routes.rb").write_text(routes_rb)
        provider = RailsProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("config/routes.rb")
        assert ctx is not None
        assert "rails-route" in ctx.tags
        # namespace :api should prefix all routes with /api
