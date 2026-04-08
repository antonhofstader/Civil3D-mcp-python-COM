"""
setup.py  –  Legacy setuptools entry point
==========================================
Kept alongside pyproject.toml for compatibility with:
  • pip < 21.3 (older Windows Python environments)
  • editable installs that need an explicit setup.py
  • tools that call `python setup.py --version` etc.

All real configuration lives in pyproject.toml.
Do NOT duplicate dependency lists here.
"""
from setuptools import setup

if __name__ == "__main__":
    setup()
