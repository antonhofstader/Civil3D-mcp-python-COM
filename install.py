"""
install.py  –  civil3d-mcp dependency installer
=================================================
Run this script once to set up the full Python environment needed by the
civil3d-mcp FastMCP server.

Usage
-----
    python install.py             # install runtime dependencies only
    python install.py --dev       # also install dev / test dependencies
    python install.py --verify    # install + run import verification
    python install.py --dev --verify

What it does
------------
1. Validates Python version  (3.11+) and OS (Windows only)
2. Upgrades pip, setuptools, wheel to recent stable versions
3. Installs runtime dependencies:
       fastmcp, pywin32, pythonnet, pydantic
4. Installs the civil3d-mcp package itself in editable mode (pip install -e .)
5. [--dev]    installs pytest, pytest-asyncio, black, ruff, mypy
6. [--verify] imports every key module and reports any failures
7. Prints a quick-start summary
"""

from __future__ import annotations

import argparse
import importlib
import platform
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Colour helpers (works on Windows 10 1511 + / any terminal that supports ANSI)
# ---------------------------------------------------------------------------
_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


OK   = _c("32;1", "OK")
FAIL = _c("31;1", "FAIL")
INFO = _c("36",   "INFO")
WARN = _c("33",   "WARN")
HEAD = _c("1",    "{}")


def _head(text: str) -> None:
    width = 60
    print()
    print(_c("1", "=" * width))
    print(_c("1", f"  {text}"))
    print(_c("1", "=" * width))


def _step(text: str) -> None:
    print(f"\n  {_c('36', '>>')} {text}")


def _ok(text: str) -> None:
    print(f"      [{OK}]  {text}")


def _fail(text: str) -> None:
    print(f"      [{FAIL}]  {text}")


def _warn(text: str) -> None:
    print(f"      [{WARN}]  {text}")


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------

def check_environment() -> bool:
    """Return True only if the environment is safe to proceed."""
    passed = True

    _step("Checking Python version")
    vi = sys.version_info
    version_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    if (vi.major, vi.minor) >= (3, 11):
        _ok(f"Python {version_str}")
    else:
        _fail(
            f"Python {version_str} detected — civil3d-mcp requires Python 3.11 or newer.\n"
            "        Download: https://www.python.org/downloads/"
        )
        passed = False

    _step("Checking operating system")
    if platform.system() == "Windows":
        _ok(f"Windows {platform.version()}")
    else:
        _fail(
            f"OS '{platform.system()}' detected — civil3d-mcp requires Windows "
            "(COM automation via pywin32 / pythonnet is Windows-only)."
        )
        passed = False

    return passed


# ---------------------------------------------------------------------------
# pip runner
# ---------------------------------------------------------------------------

def _pip(*args: str, check: bool = True) -> int:
    """Run a pip command using the current interpreter."""
    cmd = [sys.executable, "-m", "pip", *args]
    result = subprocess.run(cmd, check=False)  # noqa: S603
    if check and result.returncode != 0:
        _fail(f"pip command failed (exit {result.returncode}): {' '.join(args)}")
        sys.exit(result.returncode)
    return result.returncode


# ---------------------------------------------------------------------------
# Package lists
# ---------------------------------------------------------------------------

RUNTIME_PACKAGES = [
    "fastmcp>=0.4.0",
    "pywin32>=306",
    "pythonnet>=3.0.3",
    "pydantic>=2.0",
]

BUILD_BOOTSTRAP = [
    "pip>=24.0",
    "setuptools>=68",
    "wheel",
]

DEV_PACKAGES = [
    "pytest>=7.4",
    "pytest-asyncio>=0.23",
    "black>=24.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

def upgrade_bootstrap() -> None:
    _step("Upgrading pip / setuptools / wheel")
    _pip("install", "--upgrade", *BUILD_BOOTSTRAP)
    _ok("pip, setuptools, wheel up to date")


def install_runtime() -> None:
    _step("Installing runtime dependencies")
    for pkg in RUNTIME_PACKAGES:
        print(f"        installing  {pkg}")
        _pip("install", pkg, "--upgrade")
    _ok("All runtime packages installed")


def install_dev() -> None:
    _step("Installing dev / test dependencies")
    for pkg in DEV_PACKAGES:
        print(f"        installing  {pkg}")
        _pip("install", pkg, "--upgrade")
    _ok("All dev packages installed")


def install_package_editable() -> None:
    """Install the civil3d-mcp package itself in editable mode."""
    _step("Installing civil3d-mcp package (editable)")
    project_root = Path(__file__).parent
    _pip("install", "--editable", str(project_root))
    _ok("civil3d-mcp installed in editable mode")


# ---------------------------------------------------------------------------
# Post-install verification
# ---------------------------------------------------------------------------

VERIFY_MODULES: list[tuple[str, str]] = [
    ("mcp.server.fastmcp",  "FastMCP framework  (mcp / fastmcp)"),
    ("pydantic",            "Pydantic"),
    ("win32com.client",     "pywin32  (win32com)"),
    ("pythoncom",           "pywin32  (pythoncom)"),
    ("clr",                 "pythonnet  (clr)"),
    ("civil3d_mcp.server",  "civil3d-mcp server"),
    ("civil3d_mcp.client",  "civil3d-mcp client"),
    ("civil3d_mcp.tools_surfaces", "civil3d-mcp tools_surfaces"),
]


def verify_imports() -> bool:
    _step("Verifying imports")
    all_ok = True
    for module, label in VERIFY_MODULES:
        try:
            importlib.import_module(module)
            _ok(label)
        except ImportError as exc:
            _fail(f"{label}  →  {exc}")
            all_ok = False
        except Exception as exc:  # noqa: BLE001  (e.g. COM not available in CI)
            _warn(f"{label}  →  {type(exc).__name__}: {exc}")
    return all_ok


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(dev: bool) -> None:
    _head("Setup complete")
    print()
    print("  Next steps:")
    print()
    print("  1. Open Autodesk Civil 3D and load a drawing.")
    print()
    print("  2. Start the MCP server:")
    print("       python -m civil3d_mcp.server")
    print("       # or, after editable install:")
    print("       civil3d-mcp")
    print()
    print("  3. Configure your MCP client (Claude Desktop, etc.) using the")
    print("     snippet in  claude_desktop_config_snippet.json")
    print()
    if dev:
        print("  4. Run tests:")
        print("       pytest")
        print()
    print("  Environment variables (optional):")
    print("    CIVIL3D_BIN_PATH  – Path to the Civil 3D install folder")
    print('                        e.g.  set CIVIL3D_BIN_PATH=C:\\Program Files\\Autodesk\\AutoCAD 2026\\C3D')
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install all civil3d-mcp dependencies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install dev / test dependencies (pytest, black, ruff, mypy).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run import verification after installation.",
    )
    args = parser.parse_args()

    _head("civil3d-mcp  –  Dependency Installer")

    if not check_environment():
        print()
        print(_c("31;1", "  Environment check failed. Resolve the issues above and re-run."))
        sys.exit(1)

    upgrade_bootstrap()
    install_runtime()

    if args.dev:
        install_dev()

    install_package_editable()

    if args.verify:
        ok = verify_imports()
        if not ok:
            print()
            _warn(
                "Some imports failed. If pywin32/pythonnet warnings appear, "
                "that is expected when Civil 3D is not running. "
                "COM errors at runtime will resolve once Civil 3D is open."
            )

    print_summary(dev=args.dev)


if __name__ == "__main__":
    main()
