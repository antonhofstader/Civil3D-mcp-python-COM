"""
conftest.py  –  pytest configuration
Adds src/ to sys.path so civil3d_mcp can be imported without pip install -e .
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
