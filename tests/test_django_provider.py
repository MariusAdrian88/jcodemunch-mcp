"""Tests for django.py provider."""

from pathlib import Path

import pytest

from jcodemunch_mcp.parser.context.django import DjangoProvider


class TestDjangoDetection:
    """Tests for Django detection."""

    def test_django_detect(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("django>=4.0\n")
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True

    def test_django_pyproject(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        pyproject = """
[project]
dependencies = ["django>=4.0"]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject)
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True

    def test_no_manage_py(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("django>=4.0\n")
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is False

    def test_no_django_dep(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("flask>=2.0\n")
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is False


class TestDjangoUrlExtraction:
    """Tests for Django URL extraction."""

    def test_basic_urls(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("django>=4.0\n")
        urls_py = """
from django.urls import path
from . import views

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('users/<int:id>/', views.user_detail, name='user_detail'),
    path('api/v1/users/', views.api_user_list, name='api_user_list'),
]
"""
        (tmp_path / "urls.py").write_text(urls_py)
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("urls.py")
        assert ctx is not None
        assert "django-url" in ctx.tags
        assert ctx.properties["framework"] == "django"
        assert "user_list" in ctx.properties["routes"] or "users/" in ctx.properties["routes"]


class TestDjangoIncludeResolution:
    """Tests for Django include() resolution."""

    def test_include_resolution(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("django>=4.0\n")
        main_urls = """
from django.urls import path, include

urlpatterns = [
    path('api/', include('api.urls')),
]
"""
        api_urls = """
from django.urls import path
from . import views

urlpatterns = [
    path('users/', views.user_list),
]
"""
        (tmp_path / "urls.py").write_text(main_urls)
        (tmp_path / "api" / "urls.py").parent.mkdir(parents=True)
        (tmp_path / "api" / "urls.py").write_text(api_urls)
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        extras = provider.get_extra_imports()
        # include() should create edges from urls.py to api/urls.py


class TestDjangoDRF:
    """Tests for Django REST Framework detection."""

    def test_drf_api_view(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("django>=4.0\ndjangorestframework>=3.14\n")
        views_py = """
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET', 'POST'])
def user_list(request):
    if request.method == 'POST':
        return Response({'id': 1}, status=201)
    return Response([])

@api_view(['GET', 'PUT', 'DELETE'])
def user_detail(request, pk):
    return Response({'id': pk})
"""
        (tmp_path / "views.py").write_text(views_py)
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True
        provider.load(tmp_path)

        ctx = provider.get_file_context("views.py")
        assert ctx is not None
        # DRF decorators should be detected
