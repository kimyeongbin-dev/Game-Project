"""
Health check test - Basic sanity tests
"""
import pytest
import sys


def test_python_version():
    """Verify Python version."""
    assert sys.version_info >= (3, 9), "Python 3.9+ required"


def test_imports():
    """Verify required packages can be imported."""
    import fastapi
    import sqlalchemy
    import pydantic

    assert fastapi is not None
    assert sqlalchemy is not None
    assert pydantic is not None
