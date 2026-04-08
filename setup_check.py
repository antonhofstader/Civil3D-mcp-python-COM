"""
setup_check.py  –  civil3d-mcp pre-flight environment checker
==============================================================
Run this BEFORE starting the MCP server to verify that all
dependencies and system conditions are met.

Usage:
    python setup_check.py
    python setup_check.py --fix      # attempt auto-fixes (pip install)
    python setup_check.py --json     # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    fix_hint: str = ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_platform() -> CheckResult:
    ok = platform.system() == "Windows"
    return CheckResult(
        name="Windows OS",
        passed=ok,
        detail=f"Detected: {platform.system()} {platform.release()}",
        fix_hint="COM automation requires Windows 10 or 11." if not ok else "",
    )


def check_python_version() -> CheckResult:
    v = sys.version_info
    ok = (v.major == 3 and v.minor >= 11)
    return CheckResult(
        name="Python >= 3.11",
        passed=ok,
        detail=f"Detected: Python {v.major}.{v.minor}.{v.micro}",
        fix_hint=(
            "Install Python 3.11+ from https://python.org "
            "and re-run this script."
        ) if not ok else "",
    )


def check_python_arch() -> CheckResult:
    bits = "64-bit" if sys.maxsize > 2**32 else "32-bit"
    ok = sys.maxsize > 2**32
    return CheckResult(
        name="Python 64-bit",
        passed=ok,
        detail=f"Detected: {bits}",
        fix_hint=(
            "Civil 3D is 64-bit. Install the 64-bit Python distribution."
        ) if not ok else "",
    )


def _import_ok(module: str) -> tuple[bool, str]:
    try:
        __import__(module)
        mod = sys.modules[module]
        ver = getattr(mod, "__version__", "unknown")
        return True, ver
    except ImportError as exc:
        return False, str(exc)


def check_fastmcp() -> CheckResult:
    ok, ver = _import_ok("mcp")
    return CheckResult(
        name="fastmcp / mcp package",
        passed=ok,
        detail=f"version: {ver}" if ok else ver,
        fix_hint="pip install fastmcp" if not ok else "",
    )


def check_win32com() -> CheckResult:
    ok, ver = _import_ok("win32com.client")
    return CheckResult(
        name="pywin32 (win32com)",
        passed=ok,
        detail=f"version: {ver}" if ok else ver,
        fix_hint="pip install pywin32" if not ok else "",
    )


def check_pythoncom() -> CheckResult:
    ok, ver = _import_ok("pythoncom")
    return CheckResult(
        name="pythoncom",
        passed=ok,
        detail="present" if ok else ver,
        fix_hint="pip install pywin32  (pythoncom ships with pywin32)" if not ok else "",
    )


def check_pythonnet() -> CheckResult:
    ok, ver = _import_ok("clr")
    return CheckResult(
        name="pythonnet (clr)",
        passed=ok,
        detail=f"version: {ver}" if ok else ver,
        fix_hint="pip install pythonnet" if not ok else "",
    )


def check_pydantic() -> CheckResult:
    ok, ver = _import_ok("pydantic")
    return CheckResult(
        name="pydantic",
        passed=ok,
        detail=f"version: {ver}" if ok else ver,
        fix_hint="pip install pydantic" if not ok else "",
    )


# --------------- Civil 3D binary paths ---------------

_CANDIDATE_ROOTS = [
    r"C:\Program Files\Autodesk\AutoCAD 2025",
    r"C:\Program Files\Autodesk\AutoCAD 2024",
    r"C:\Program Files\Autodesk\AutoCAD 2023",
]
_REQUIRED_DLLS = ["AeccDbMgd.dll", "AeccLandMgd.dll", "acdbmgd.dll"]


def _find_civil3d_root() -> str | None:
    env_path = os.getenv("CIVIL3D_BIN_PATH", "").strip()
    if env_path and Path(env_path).is_dir():
        return env_path
    for root in _CANDIDATE_ROOTS:
        if Path(root).is_dir():
            return root
    return None


def check_civil3d_install() -> CheckResult:
    root = _find_civil3d_root()
    if root is None:
        return CheckResult(
            name="Civil 3D installation",
            passed=False,
            detail="No Civil 3D folder found in default paths.",
            fix_hint=(
                "Install Civil 3D 2023-2025, or set CIVIL3D_BIN_PATH "
                "in .env to the folder containing AeccDbMgd.dll."
            ),
        )
    return CheckResult(
        name="Civil 3D installation",
        passed=True,
        detail=f"Found: {root}",
    )


def check_autodesk_dlls() -> CheckResult:
    root = _find_civil3d_root()
    if root is None:
        return CheckResult(
            name="Autodesk .NET DLLs",
            passed=False,
            detail="Civil 3D root not found (see previous check).",
        )
    missing = [
        dll for dll in _REQUIRED_DLLS
        if not Path(root, dll).exists()
    ]
    if missing:
        return CheckResult(
            name="Autodesk .NET DLLs",
            passed=False,
            detail=f"Missing in {root}: {', '.join(missing)}",
            fix_hint=(
                "Ensure a full Civil 3D installation is present, "
                "or set CIVIL3D_BIN_PATH to the correct folder."
            ),
        )
    return CheckResult(
        name="Autodesk .NET DLLs",
        passed=True,
        detail=f"All found in: {root}",
    )


# --------------- Civil 3D running ---------------

def check_civil3d_running() -> CheckResult:
    """Try GetActiveObject to verify Civil 3D is currently open."""
    try:
        import win32com.client as w32  # type: ignore
    except ImportError:
        return CheckResult(
            name="Civil 3D running",
            passed=False,
            detail="pywin32 not installed – cannot check.",
            fix_hint="Install pywin32 first.",
        )

    prog_ids = [
        "AeccXUiLand.AeccApplication.14.0",
        "AeccXUiLand.AeccApplication.13.0",
        "AutoCAD.Application",
    ]
    for prog_id in prog_ids:
        try:
            app = w32.GetActiveObject(prog_id)
            doc = app.ActiveDocument
            name = getattr(doc, "Name", "(unknown)")
            return CheckResult(
                name="Civil 3D running",
                passed=True,
                detail=f"Connected via {prog_id} — active drawing: {name}",
            )
        except Exception:
            continue

    return CheckResult(
        name="Civil 3D running",
        passed=False,
        detail="Could not connect to a running Civil 3D / AutoCAD instance.",
        fix_hint=(
            "Open Civil 3D and load a drawing before starting the MCP server. "
            "This check is optional — the server will retry on first tool call."
        ),
    )


# --------------- Claude Desktop config ---------------

def check_claude_config() -> CheckResult:
    config_path = Path(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json")
    if not config_path.exists():
        return CheckResult(
            name="Claude Desktop config",
            passed=False,
            detail=f"Not found at: {config_path}",
            fix_hint=(
                "Install Claude Desktop from https://claude.ai/download, "
                "then add the civil3d-mcp entry from claude_desktop_config_snippet.json."
            ),
        )
    try:
        with open(config_path) as fh:
            cfg = json.load(fh)
        servers = cfg.get("mcpServers", {})
        if "civil3d-mcp" in servers:
            return CheckResult(
                name="Claude Desktop config",
                passed=True,
                detail=f"civil3d-mcp entry found in {config_path}",
            )
        return CheckResult(
            name="Claude Desktop config",
            passed=False,
            detail=f"civil3d-mcp entry missing from {config_path}",
            fix_hint=(
                "Add the block from claude_desktop_config_snippet.json "
                "to the mcpServers section and restart Claude Desktop."
            ),
        )
    except Exception as exc:
        return CheckResult(
            name="Claude Desktop config",
            passed=False,
            detail=f"Could not parse config: {exc}",
            fix_hint="Check that claude_desktop_config.json is valid JSON.",
        )


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------

_PIP_PACKAGES = ["fastmcp", "pywin32", "pythonnet", "pydantic"]


def auto_fix(results: list[CheckResult]) -> None:
    failed_pip = [
        r for r in results
        if not r.passed and r.fix_hint.startswith("pip install")
    ]
    if not failed_pip:
        print("\n  Nothing to auto-fix via pip.")
        return
    for r in failed_pip:
        pkg = r.fix_hint.replace("pip install", "").split("(")[0].strip()
        print(f"\n  Installing: {pkg}")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CHECKS: list[Callable[[], CheckResult]] = [
    check_platform,
    check_python_version,
    check_python_arch,
    check_fastmcp,
    check_win32com,
    check_pythoncom,
    check_pythonnet,
    check_pydantic,
    check_civil3d_install,
    check_autodesk_dlls,
    check_civil3d_running,
    check_claude_config,
]

_PASS = "  [PASS]"
_FAIL = "  [FAIL]"
_WARN = "  [WARN]"


def run_checks(fix: bool = False, as_json: bool = False) -> int:
    results: list[CheckResult] = []

    if not as_json:
        print()
        print("=" * 60)
        print("  civil3d-mcp  —  environment check")
        print("=" * 60)

    for check_fn in CHECKS:
        result = check_fn()
        results.append(result)
        if not as_json:
            status = _PASS if result.passed else _FAIL
            print(f"\n{status}  {result.name}")
            print(f"        {result.detail}")
            if not result.passed and result.fix_hint:
                print(f"        → {result.fix_hint}")

    n_pass = sum(1 for r in results if r.passed)
    n_fail = len(results) - n_pass

    if as_json:
        print(json.dumps(
            {
                "summary": {"passed": n_pass, "failed": n_fail},
                "checks": [
                    {
                        "name": r.name,
                        "passed": r.passed,
                        "detail": r.detail,
                        "fix_hint": r.fix_hint,
                    }
                    for r in results
                ],
            },
            indent=2,
        ))
        return 0 if n_fail == 0 else 1

    print()
    print("=" * 60)
    print(f"  Result: {n_pass} passed, {n_fail} failed")
    print("=" * 60)

    # Civil 3D running is advisory — doesn't block
    hard_failures = [
        r for r in results
        if not r.passed and r.name != "Civil 3D running"
    ]

    if not hard_failures:
        print()
        print("  All required checks passed.")
        if any(not r.passed for r in results):
            print("  (Civil 3D running check is advisory — start Civil 3D before")
            print("   launching the MCP server.)")
        print()
        print("  Next steps:")
        print("  1. Open Civil 3D and load a drawing")
        print("  2. Start Claude Desktop")
        print("  3. Look for the hammer icon (🔨) in the toolbar")
        print()
    else:
        print()
        print("  Fix the failures above before running the server.")
        if fix:
            auto_fix(results)
        else:
            print("  Run with --fix to attempt automatic pip installs.")
        print()

    return 0 if not hard_failures else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="civil3d-mcp pre-flight environment checker"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt auto-fixes (pip install missing packages)",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()
    sys.exit(run_checks(fix=args.fix, as_json=args.as_json))


if __name__ == "__main__":
    main()
