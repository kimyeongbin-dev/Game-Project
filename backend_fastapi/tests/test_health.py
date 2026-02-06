"""
Health check test - Workflow verification
"""
import pytest


def test_workflow_trigger():
    """Simple test to verify GitHub Actions workflow is triggered."""
    assert True, "Workflow test passed"


def test_python_environment():
    """Verify Python environment is set up correctly."""
    import sys
    assert sys.version_info >= (3, 9), "Python 3.9+ required"
