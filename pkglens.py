#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Package Dashboard: pip/pip3, Homebrew, npm (global)
Usage:
  python3 pkg_dashboard.py           # generate HTML and print path
  python3 pkg_dashboard.py --open    # also open in your browser
  python3 pkg_dashboard.py --port 0  # pick a random ephemeral port when serving
"""
import argparse
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / ".pkg_dashboard_build"
OUT_DIR.mkdir(exist_ok=True)
HTML_PATH = OUT_DIR / "index.html"
DATA_PATH = OUT_DIR / "packages.json"
HISTORY_PATH = OUT_DIR / "uninstall_history.json"
PREVIOUS_PACKAGES_PATH = OUT_DIR / "previous_packages.json"
VERIFICATION_STATUS_PATH = OUT_DIR / "verification_status.json"

def norm(v):
    """Normalize values to clean strings for display/hash keys."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        try:
            return ", ".join(map(str, v))
        except Exception:
            return str(v)
    try:
        return str(v)
    except Exception:
        return ""

def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None

def print_progress(message):
    """Print progress message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def run_cmd(cmd, timeout=60):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
        return out.decode("utf-8", errors="replace")
    except Exception:
        return ""

def print_progress(message):
    """Print progress message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_directory_size(path):
    """Calculate directory size in bytes."""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size
    except Exception:
        return 0

def format_size(size_bytes):
    """Format bytes into human readable format."""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def get_package_size(manager, name, path):
    """Get package size based on manager type."""
    try:
        if manager == "pip (this Python)" or manager.startswith("pip"):
            # For pip packages, calculate size of the package directory
            if path and os.path.exists(path):
                return get_directory_size(path)
            # Try to find package location
            try:
                if sys.version_info >= (3, 8):
                    import importlib.metadata as md
                else:
                    md = importlib.import_module("importlib_metadata")
                dist = md.distribution(name)
                if dist and dist.files:
                    package_path = dist.locate_file(dist.files[0]).parent
                    return get_directory_size(str(package_path))
            except Exception:
                pass
        elif manager == "brew":
            # For Homebrew, get formula size
            out = run_cmd(["brew", "info", "--json=v2", name])
            if out.strip():
                try:
                    data = json.loads(out)
                    for coll in ("formulae", "casks"):
                        for entry in data.get(coll, []) or []:
                            if entry.get("name") == name:
                                # Try to get installed size
                                if entry.get("installed"):
                                    for install in entry["installed"]:
                                        if install.get("size"):
                                            return install["size"]
                except Exception:
                    pass
        elif manager == "npm (global)":
            # For npm, get package directory size
            npm_prefix = run_cmd(["npm", "config", "get", "prefix"]).strip()
            if npm_prefix:
                package_path = os.path.join(npm_prefix, "lib", "node_modules", name)
                if os.path.exists(package_path):
                    return get_directory_size(package_path)
    except Exception:
        pass
    return 0

def load_uninstall_history():
    """Load uninstall history from file."""
    try:
        if HISTORY_PATH.exists():
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def save_uninstall_history(history):
    """Save uninstall history to file."""
    try:
        HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass

def add_to_uninstall_history(package_info):
    """Add package to uninstall history."""
    history = load_uninstall_history()
    history.append({
        "name": package_info["name"],
        "version": package_info["version"],
        "manager": package_info["manager"],
        "uninstalled_at": datetime.now().isoformat(),
        "size": package_info.get("size", 0),
        "source": "dashboard_uninstall"
    })
    # Keep only last 100 entries
    if len(history) > 100:
        history = history[-100:]
    save_uninstall_history(history)

def save_packages_snapshot(packages):
    """Save current packages as a snapshot for comparison."""
    try:
        PREVIOUS_PACKAGES_PATH.write_text(json.dumps(packages, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_packages_snapshot():
    """Load previous packages snapshot."""
    try:
        if PREVIOUS_PACKAGES_PATH.exists():
            return json.loads(PREVIOUS_PACKAGES_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def detect_missing_packages(current_packages):
    """Detect packages that were uninstalled outside the dashboard."""
    previous_packages = load_packages_snapshot()
    if not previous_packages:
        return []
    
    # Create sets for easy comparison
    current_set = {(p.get("manager", ""), p.get("name", "")) for p in current_packages}
    previous_set = {(p.get("manager", ""), p.get("name", "")) for p in previous_packages}
    
    # Find packages that were in previous but not in current
    missing_packages = previous_set - current_set
    
    # Get full package info for missing packages
    missing_info = []
    for manager, name in missing_packages:
        for pkg in previous_packages:
            if pkg.get("manager") == manager and pkg.get("name") == name:
                missing_info.append(pkg)
                break
    
    return missing_info

def add_missing_packages_to_history(missing_packages):
    """Add detected missing packages to uninstall history."""
    if not missing_packages:
        return
    
    history = load_uninstall_history()
    
    for package in missing_packages:
        # Check if this package is already in history
        already_exists = any(
            h.get("name") == package.get("name") and 
            h.get("manager") == package.get("manager") and
            h.get("source") == "detected_missing"
            for h in history
        )
        
        if not already_exists:
            history.append({
                "name": package.get("name", ""),
                "version": package.get("version", ""),
                "manager": package.get("manager", ""),
                "uninstalled_at": datetime.now().isoformat(),
                "size": package.get("size", 0),
                "source": "detected_missing"
            })
    
    # Keep only last 100 entries
    if len(history) > 100:
        history = history[-100:]
    save_uninstall_history(history)

def save_verification_status(verification_data):
    """Save verification status to file."""
    try:
        VERIFICATION_STATUS_PATH.write_text(json.dumps(verification_data, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_verification_status():
    """Load verification status from file."""
    try:
        if VERIFICATION_STATUS_PATH.exists():
            return json.loads(VERIFICATION_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_verification_status(verification_data):
    """Save verification status to file."""
    try:
        VERIFICATION_STATUS_PATH.write_text(json.dumps(verification_data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Error saving verification status: {e}")

def update_verification_status(manager, name, status_data):
    """Update verification status for a specific package."""
    verification_data = load_verification_status()
    key = f"{manager}-{name}"
    verification_data[key] = {
        "status": status_data.get("status", "unknown"),
        "message": status_data.get("message", ""),
        "verified_at": datetime.now().isoformat()
    }
    save_verification_status(verification_data)

def verify_package_integrity(manager, name):
    """Verify package integrity based on manager type."""
    try:
        if manager == "pip (this Python)" or manager.startswith("pip"):
            # For pip packages, check if package can be imported and show version
            try:
                # Try to import the package
                module = __import__(name)
                version = getattr(module, '__version__', 'unknown')
                
                # Check if package has any known security issues via pip-audit if available
                try:
                    result = run_cmd([sys.executable, "-m", "pip_audit", "--format", "json", "--only", name])
                    if result.strip():
                        try:
                            audit_data = json.loads(result)
                            if audit_data.get("vulnerabilities"):
                                vulns = len(audit_data["vulnerabilities"])
                                result_data = {"status": "failed", "message": f"Package has {vulns} known vulnerabilities"}
                                update_verification_status(manager, name, result_data)
                                return result_data
                        except json.JSONDecodeError:
                            pass
                except Exception:
                    # pip-audit not available or failed, continue with basic check
                    pass
                
                result_data = {"status": "verified", "message": f"Package verified (version: {version})"}
                update_verification_status(manager, name, result_data)
                return result_data
            except ImportError:
                result_data = {"status": "failed", "message": "Package cannot be imported"}
                update_verification_status(manager, name, result_data)
                return result_data
            except Exception as e:
                result_data = {"status": "failed", "message": f"Import error: {str(e)}"}
                update_verification_status(manager, name, result_data)
                return result_data
        elif manager == "brew":
            # Use brew audit for integrity check
            result = run_cmd(["brew", "audit", "--strict", name])
            if "No problems" in result or result.strip() == "":
                result_data = {"status": "verified", "message": "Package integrity verified"}
                update_verification_status(manager, name, result_data)
                return result_data
            else:
                result_data = {"status": "failed", "message": f"Audit issues: {result.strip()}"}
                update_verification_status(manager, name, result_data)
                return result_data
        elif manager == "npm (global)":
            # Check npm package integrity
            npm_prefix = run_cmd(["npm", "config", "get", "prefix"]).strip()
            if npm_prefix:
                package_path = os.path.join(npm_prefix, "lib", "node_modules", name)
                if os.path.exists(package_path):
                    result = run_cmd(["npm", "audit", "--audit-level=moderate", "--prefix", package_path])
                    if "found 0 vulnerabilities" in result:
                        result_data = {"status": "verified", "message": "Package integrity verified"}
                        update_verification_status(manager, name, result_data)
                        return result_data
                    else:
                        result_data = {"status": "failed", "message": "Vulnerabilities found"}
                        update_verification_status(manager, name, result_data)
                        return result_data
            result_data = {"status": "unknown", "message": "Could not verify npm package"}
            update_verification_status(manager, name, result_data)
            return result_data
        else:
            result_data = {"status": "unknown", "message": f"Unknown manager: {manager}"}
            update_verification_status(manager, name, result_data)
            return result_data
    except Exception as e:
        result_data = {"status": "error", "message": f"Error verifying {name}: {str(e)}"}
        update_verification_status(manager, name, result_data)
        return result_data

def detect_package_conflicts():
    """Detect package conflicts and issues."""
    conflicts = []
    
    try:
        # Load current package data
        if DATA_PATH.exists():
            packages = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        else:
            return conflicts
        
        # Group packages by manager
        pip_packages = [p for p in packages if p.get("manager", "").startswith("pip")]
        brew_packages = [p for p in packages if p.get("manager") == "brew"]
        npm_packages = [p for p in packages if p.get("manager") == "npm (global)"]
        
        # Check for duplicate packages across managers
        all_names = [p.get("name", "").lower() for p in packages]
        duplicates = {}
        for name in all_names:
            if all_names.count(name) > 1:
                duplicates[name] = [p for p in packages if p.get("name", "").lower() == name]
        
        for name, pkgs in duplicates.items():
            if len(pkgs) > 1:
                conflicts.append({
                    "type": "duplicate",
                    "severity": "medium",
                    "title": f"Duplicate package: {name}",
                    "description": f"Found {len(pkgs)} installations of {name}",
                    "packages": pkgs,
                    "suggestion": "Consider removing duplicate installations"
                })
        
        # Check pip package conflicts
        if pip_packages:
            try:
                result = run_cmd([sys.executable, "-m", "pip", "check"])
                if "No broken requirements found" not in result:
                    conflicts.append({
                        "type": "dependency",
                        "severity": "high",
                        "title": "Python dependency conflicts",
                        "description": "Broken requirements detected",
                        "details": result.strip(),
                        "suggestion": "Run 'pip check' to see details"
                    })
            except Exception:
                pass
        
        # Check Homebrew conflicts
        if brew_packages:
            try:
                result = run_cmd(["brew", "doctor"])
                if "Your system is ready to brew" not in result:
                    conflicts.append({
                        "type": "system",
                        "severity": "medium",
                        "title": "Homebrew system issues",
                        "description": "Homebrew doctor found issues",
                        "details": result.strip(),
                        "suggestion": "Run 'brew doctor' to fix issues"
                    })
            except Exception:
                pass
        
        # Check for large packages that might be duplicates
        large_packages = [p for p in packages if p.get("size", 0) > 100 * 1024 * 1024]  # > 100MB
        if len(large_packages) > 5:
            conflicts.append({
                "type": "storage",
                "severity": "low",
                "title": "Multiple large packages",
                "description": f"Found {len(large_packages)} packages larger than 100MB",
                "packages": large_packages,
                "suggestion": "Consider reviewing large packages for cleanup"
            })
        
    except Exception as e:
        conflicts.append({
            "type": "error",
            "severity": "high",
            "title": "Error detecting conflicts",
            "description": f"Failed to analyze packages: {str(e)}",
            "suggestion": "Check system permissions and package manager status"
        })
    
    return conflicts

def uninstall_package(manager, name):
    """Uninstall a package based on its manager."""
    try:
        if manager == "pip (this Python)" or manager.startswith("pip"):
            # Use pip uninstall
            result = run_cmd([sys.executable, "-m", "pip", "uninstall", "-y", name])
            return {"success": True, "message": f"Uninstalled {name} via pip"}
        elif manager == "brew":
            # Use brew uninstall
            result = run_cmd(["brew", "uninstall", name])
            return {"success": True, "message": f"Uninstalled {name} via Homebrew"}
        elif manager == "npm (global)":
            # Use npm uninstall -g
            result = run_cmd(["npm", "uninstall", "-g", name])
            return {"success": True, "message": f"Uninstalled {name} via npm"}
        else:
            return {"success": False, "message": f"Unknown manager: {manager}"}
    except Exception as e:
        return {"success": False, "message": f"Error uninstalling {name}: {str(e)}"}

def gather_pip_importlib():
    """List packages visible to the CURRENT Python interpreter via importlib.metadata."""
    print_progress("Scanning Python packages (current environment)...")
    items = []
    try:
        if sys.version_info >= (3, 8):
            import importlib.metadata as md
        else:
            md = importlib.import_module("importlib_metadata")  # may not be installed
        for dist in md.distributions():
            # dist.metadata can be an email.message.Message; use .get
            meta = getattr(dist, "metadata", None)
            name = ""
            if meta is not None:
                try:
                    name = meta.get("Name", "")  # Message.get
                except Exception:
                    name = ""
            if not name:
                try:
                    name = dist.metadata["Name"]  # type: ignore[index]
                except Exception:
                    name = getattr(dist, "name", "")
            version = getattr(dist, "version", "") or ""
            path = ""
            try:
                if hasattr(dist, "files") and dist.files and hasattr(dist, "locate_file"):
                    path = str(dist.locate_file(dist.files[0]).parent)
            except Exception:
                path = ""
            
            # Calculate package size
            size = get_package_size("pip (this Python)", name, path)
            
            items.append({
                "manager": "pip (this Python)",
                "name": norm(name),
                "version": norm(version),
                "path": norm(path),
                "source": "importlib.metadata",
                "size": size,
                "size_formatted": format_size(size)
            })
    except Exception:
        # ignore if importlib_metadata not available (py<3.8 without backport)
        pass
    print_progress(f"Found {len(items)} Python packages")
    return items

def gather_pip_cli(bin_name="pip"):
    """pip list --format=json via a given pip binary."""
    if not cmd_exists(bin_name):
        return []
    print_progress(f"Scanning {bin_name} packages...")
    out = run_cmd([bin_name, "list", "--format=json"])
    items = []
    parsed = None
    try:
        parsed = json.loads(out) if out.strip().startswith("[") else None
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        for it in parsed:
            name = norm(it.get("name", ""))
            size = get_package_size(bin_name, name, "")
            items.append({
                "manager": bin_name,
                "name": name,
                "version": norm(it.get("version", "")),
                "path": "",
                "source": f"{bin_name} list --format=json",
                "size": size,
                "size_formatted": format_size(size)
            })
        print_progress(f"Found {len(items)} {bin_name} packages")
        return items
    # fallback: try plain text (first column name, second version)
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or ln.lower().startswith("package"):
            continue
        parts = ln.split()
        if len(parts) >= 2:
            name = norm(parts[0])
            size = get_package_size(bin_name, name, "")
            items.append({
                "manager": bin_name,
                "name": name,
                "version": norm(parts[1]),
                "path": "",
                "source": f"{bin_name} list",
                "size": size,
                "size_formatted": format_size(size)
            })
    print_progress(f"Found {len(items)} {bin_name} packages")
    return items

def gather_brew():
    """Prefer brew info --json=v2 --installed; fallback to brew list --versions."""
    if not cmd_exists("brew"):
        return []
    print_progress("Scanning Homebrew packages...")
    items = []
    
    # Get Homebrew prefix for path detection
    brew_prefix = run_cmd(["brew", "--prefix"]).strip()
    
    out = run_cmd(["brew", "info", "--json=v2", "--installed"])
    if out.strip():
        try:
            data = json.loads(out)
            # formulae + casks are both possible in v2
            for coll in ("formulae", "casks"):
                for entry in data.get(coll, []) or []:
                    name = norm(entry.get("name", ""))
                    version = ""
                    path = ""
                    
                    if entry.get("installed"):
                        try:
                            version = norm(entry["installed"][-1].get("version", "") or "")
                            # Get installation path
                            if entry.get("installed"):
                                for install in entry["installed"]:
                                    if install.get("installed_on_request"):
                                        path = os.path.join(brew_prefix, "opt", name)
                                        break
                        except Exception:
                            version = ""
                    elif entry.get("versions"):
                        version = norm(entry["versions"].get("stable", "") or "")
                    
                    # Try to find the actual path
                    if not path:
                        # Check common Homebrew paths
                        possible_paths = [
                            os.path.join(brew_prefix, "opt", name),
                            os.path.join(brew_prefix, "Cellar", name),
                            os.path.join(brew_prefix, "Caskroom", name)
                        ]
                        for p in possible_paths:
                            if os.path.exists(p):
                                path = p
                                break
                    
                    size = get_package_size("brew", name, path)
                    items.append({
                        "manager": "brew",
                        "name": name,
                        "version": version,
                        "path": path,
                        "source": "brew info --json=v2 --installed",
                        "size": size,
                        "size_formatted": format_size(size)
                    })
            print_progress(f"Found {len(items)} Homebrew packages")
            return items
        except Exception:
            pass
    
    # fallback: simple list
    out = run_cmd(["brew", "list", "--versions"])
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # e.g. "wget 1.21.3_1"
        parts = ln.split()
        if len(parts) >= 2:
            name = norm(parts[0])
            version = norm(" ".join(parts[1:]))
            
            # Try to find the actual path
            path = ""
            possible_paths = [
                os.path.join(brew_prefix, "opt", name),
                os.path.join(brew_prefix, "Cellar", name),
                os.path.join(brew_prefix, "Caskroom", name)
            ]
            for p in possible_paths:
                if os.path.exists(p):
                    path = p
                    break
            
            size = get_package_size("brew", name, path)
            items.append({
                "manager": "brew",
                "name": name,
                "version": version,
                "path": path,
                "source": "brew list --versions",
                "size": size,
                "size_formatted": format_size(size)
            })
    print_progress(f"Found {len(items)} Homebrew packages")
    return items

def gather_npm():
    """npm -g ls --depth=0 --json (global)."""
    if not cmd_exists("npm"):
        return []
    print_progress("Scanning npm packages (global)...")
    out = run_cmd(["npm", "-g", "ls", "--depth=0", "--json"])
    items = []
    try:
        data = json.loads(out)
        deps = data.get("dependencies", {}) or {}
        for name, meta in deps.items():
            version = ""
            if isinstance(meta, dict):
                version = norm(meta.get("version", ""))
            
            size = get_package_size("npm (global)", name, "")
            items.append({
                "manager": "npm (global)",
                "name": norm(name),
                "version": version,
                "path": "",
                "source": "npm -g ls --depth=0 --json",
                "size": size,
                "size_formatted": format_size(size)
            })
    except Exception:
        # fallback: npm -g ls --depth=0 (text)
        for ln in out.splitlines():
            ln = ln.strip()
            # lines often like: ├── typescript@5.4.5
            if "──" in ln and "@" in ln:
                try:
                    part = ln.split("──", 1)[1].strip()
                    name, version = part.split("@", 1)
                    size = get_package_size("npm (global)", name, "")
                    items.append({
                        "manager": "npm (global)",
                        "name": norm(name),
                        "version": norm(version),
                        "path": "",
                        "source": "npm -g ls --depth=0",
                        "size": size,
                        "size_formatted": format_size(size)
                    })
                except Exception:
                    pass
    print_progress(f"Found {len(items)} npm packages")
    return items

def dedupe(items):
    """Deduplicate by (manager, name, version). Coerce to strings to avoid unhashable types."""
    seen = set()
    out = []
    for it in items:
        m = norm(it.get("manager", ""))
        n = norm(it.get("name", ""))
        v = norm(it.get("version", ""))
        key = (m, n, v)
        if key in seen:
            continue
        seen.add(key)
        # normalize stored values as well for a clean table
        it["manager"], it["name"], it["version"] = m, n, v
        it["path"] = norm(it.get("path", ""))
        it["source"] = norm(it.get("source", ""))
        out.append(it)
    return out

def collect_all():
    print_progress("Starting package scan...")
    all_items = []
    # Current Python env (importlib)
    all_items += gather_pip_importlib()
    # pip & pip3 CLIs (they might be same or different)
    all_items += gather_pip_cli("pip")
    if shutil.which("pip3") and shutil.which("pip3") != shutil.which("pip"):
        all_items += gather_pip_cli("pip3")
    # Homebrew
    all_items += gather_brew()
    # npm (global)
    all_items += gather_npm()
    
    print_progress("Deduplicating packages...")
    deduped = dedupe(all_items)
    print_progress(f"Scan complete! Found {len(deduped)} unique packages")
    return deduped

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Local Packages Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { --bg:#0b1220; --card:#11192a; --soft:#1a2336; --text:#e9eefb; --muted:#9db0cc; --accent:#8ab4ff; }
  html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,'Helvetica Neue',Arial,'Noto Sans',sans-serif;}
  .wrap{max-width:1400px;margin:40px auto;padding:0 16px;}
  h1{font-weight:700;letter-spacing:.2px;margin:0 0 18px}
  .bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}
  .card{background:var(--card);border:1px solid #1f2a44;border-radius:16px;padding:16px;box-shadow:0 6px 18px rgba(0,0,0,.2)}
  input[type="search"]{flex:1;min-width:240px;background:var(--soft);border:1px solid #24314f;border-radius:12px;padding:10px 12px;color:var(--text);outline:none}
  select,button{background:var(--soft);border:1px solid #24314f;border-radius:12px;padding:10px 12px;color:var(--text);cursor:pointer}
  button:hover,select:hover,input[type=search]:focus{border-color:#31508d}
  table{width:100%;border-collapse:separate;border-spacing:0}
  th,td{padding:12px 10px;text-align:left}
  th{position:sticky;top:0;background:linear-gradient(180deg,var(--card),#10182a);z-index:2;border-bottom:1px solid #223054}
  tr{border-bottom:1px solid #172445}
  tr:hover{background:#0f182c}
  .pill{display:inline-block;padding:.2rem .6rem;border-radius:999px;background:#15264a;color:#a7c5ff;border:1px solid #294782;font-size:.85rem}
  .muted{color:var(--muted)}
  .footer{margin-top:14px;color:var(--muted);font-size:.9rem}
  .actions{display:flex;gap:8px;flex-wrap:wrap}
  .uninstall-btn{background:#dc2626;border-color:#dc2626;color:white;font-size:.8rem;padding:6px 10px}
  .uninstall-btn:hover{background:#b91c1c;border-color:#b91c1c}
  .history-btn{background:#059669;border-color:#059669;color:white}
  .history-btn:hover{background:#047857;border-color:#047857}
  .tabs{display:flex;gap:8px;margin-bottom:16px}
  .tab{background:var(--soft);border:1px solid #24314f;border-radius:8px;padding:8px 16px;cursor:pointer;color:var(--muted)}
  .tab.active{background:var(--accent);color:white;border-color:var(--accent)}
  .tab-content{display:none}
  .tab-content.active{display:block}
  .size-cell{font-family:monospace;font-size:.9rem}
  .total-size{font-weight:600;color:var(--accent)}
  .verify-btn{background:#059669;border-color:#059669;color:white;font-size:.8rem;padding:6px 10px}
  .verify-btn:hover{background:#047857;border-color:#047857}
  .verify-btn.verified{background:#059669;border-color:#059669}
  .verify-btn.failed{background:#dc2626;border-color:#dc2626}
  .verify-btn.unknown{background:#6b7280;border-color:#6b7280}
  .conflict-item{background:var(--soft);border:1px solid #24314f;border-radius:8px;padding:12px;margin-bottom:8px}
  .conflict-item.high{border-left:4px solid #dc2626}
  .conflict-item.medium{border-left:4px solid #f59e0b}
  .conflict-item.low{border-left:4px solid #10b981}
  .severity-badge{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.75rem;font-weight:600;text-transform:uppercase}
  .severity-badge.high{background:#dc2626;color:white}
  .severity-badge.medium{background:#f59e0b;color:white}
  .severity-badge.low{background:#10b981;color:white}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Local Packages Dashboard</h1>
    
    <div class="tabs">
      <div class="tab active" data-tab="packages">📦 Installed Packages</div>
      <div class="tab" data-tab="verification">✅ Verification Status</div>
      <div class="tab" data-tab="conflicts">⚠️ Conflicts & Issues</div>
      <div class="tab" data-tab="history">🗑️ Uninstall History</div>
    </div>
    
    <div class="tab-content active" id="packages-tab">
      <div class="card">
        <div class="bar">
          <input id="q" type="search" placeholder="Search by name/version/source…" />
          <select id="mgr">
            <option value="">All managers</option>
          </select>
          <div class="actions">
            <button id="exportCsv">Export CSV</button>
            <button id="refreshBtn">🔄 Refresh</button>
            <span id="count" class="muted"></span>
          </div>
        </div>
        <div style="overflow:auto; max-height:70vh; border-radius:12px; border:1px solid #1b294a;">
          <table id="tbl">
            <thead>
              <tr>
                <th data-k="manager">Manager</th>
                <th data-k="name">Package</th>
                <th data-k="version">Version</th>
                <th data-k="size">Size</th>
                <th data-k="path">Path</th>
                <th data-k="source">Source</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
        <div class="footer">
          <div class="total-size" id="totalSize"></div>
          <div>Tip: This shows Python (current env + pip/pip3 CLIs if found), Homebrew installs, and globally-installed npm packages.</div>
        </div>
      </div>
    </div>
    
    <div class="tab-content" id="verification-tab">
      <div class="card">
        <div class="bar">
          <input id="verificationSearch" type="search" placeholder="Search verification status…" />
          <select id="verificationFilter">
            <option value="">All statuses</option>
            <option value="verified">✅ Verified</option>
            <option value="failed">❌ Failed</option>
            <option value="unknown">❓ Unknown</option>
            <option value="unverified">⏳ Unverified</option>
          </select>
          <div class="actions">
            <button id="verifyAllBtn">🔍 Verify All</button>
            <button id="refreshVerification">🔄 Refresh</button>
            <span id="verificationCount" class="muted"></span>
          </div>
        </div>
        <div style="overflow:auto; max-height:70vh; border-radius:12px; border:1px solid #1b294a;">
          <table id="verificationTable">
            <thead>
              <tr>
                <th data-k="manager">Manager</th>
                <th data-k="name">Package</th>
                <th data-k="version">Version</th>
                <th data-k="size">Size</th>
                <th>Verification Status</th>
                <th>Message</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
        <div class="footer">
          <div class="total-size" id="verificationTotalSize"></div>
          <div>Shows verification status of all packages. Click "Verify All" to check all packages.</div>
        </div>
      </div>
    </div>
    
    <div class="tab-content" id="conflicts-tab">
      <div class="card">
        <div class="bar">
          <button id="scanConflicts">🔍 Scan for Conflicts</button>
          <button id="refreshConflicts">🔄 Refresh</button>
          <span id="conflictsCount" class="muted"></span>
        </div>
        <div id="conflictsList" style="max-height:70vh; overflow:auto;">
          <!-- Conflicts will be populated here -->
        </div>
      </div>
    </div>
    
    <div class="tab-content" id="history-tab">
      <div class="card">
        <div class="bar">
          <input id="historySearch" type="search" placeholder="Search uninstall history…" />
          <select id="historySourceFilter">
            <option value="">All sources</option>
            <option value="dashboard_uninstall">Dashboard Uninstall</option>
            <option value="detected_missing">Detected Missing</option>
          </select>
          <div class="actions">
            <button id="detectMissingBtn">🔍 Detect Missing</button>
            <button id="clearHistory">Clear History</button>
            <span id="historyCount" class="muted"></span>
          </div>
        </div>
        <div style="overflow:auto; max-height:70vh; border-radius:12px; border:1px solid #1b294a;">
          <table id="historyTable">
            <thead>
              <tr>
                <th>Package</th>
                <th>Version</th>
                <th>Manager</th>
                <th>Size</th>
                <th>Source</th>
                <th>Uninstalled</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
<script>
let data = [];
let history = [];
let verificationStatus = {}; // Track verification status for each package

async function loadVerificationStatus() {
  try {
    const response = await fetch('/api/verification-status');
    const result = await response.json();
    if (result.success) {
      verificationStatus = result.verification_status || {};
    } else {
      verificationStatus = {};
    }
  } catch (e) {
    verificationStatus = {};
  }
}

async function loadData() {
  try {
    const res = await fetch('packages.json');
    data = await res.json();
  } catch (e) {
    console.error('Failed to load packages:', e);
    data = [];
  }
}

async function loadHistory() {
  try {
    const res = await fetch('uninstall_history.json');
    history = await res.json();
  } catch (e) {
    console.error('Failed to load history:', e);
    history = [];
  }
}

function formatDate(dateStr) {
  const date = new Date(dateStr);
  return date.toLocaleString();
}

function esc(s){return (s+"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function calculateTotalSize(items) {
  return items.reduce((total, item) => total + (item.size || 0), 0);
}

function formatSize(size) {
  if (size === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024.0;
    i++;
  }
  return size.toFixed(1) + " " + units[i];
}

async function verifyPackage(manager, name) {
  const btn = document.getElementById(`verify-${manager}-${name}`);
  if (!btn) return;
  
  btn.textContent = 'Verifying...';
  btn.disabled = true;
  
  try {
    const response = await fetch('/api/verify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({manager, name})
    });
    
    const result = await response.json();
    
    if (result.success) {
      const status = result.result.status;
      btn.textContent = status === 'verified' ? '✅ Verified' : 
                       status === 'failed' ? '❌ Failed' : '❓ Unknown';
      btn.className = `verify-btn ${status}`;
      
      if (status !== 'verified') {
        alert(`${name} verification: ${result.result.message}`);
      }
    } else {
      btn.textContent = 'Error';
      btn.className = 'verify-btn unknown';
      alert(`Failed to verify ${name}: ${result.message}`);
    }
  } catch (e) {
    btn.textContent = 'Error';
    btn.className = 'verify-btn unknown';
    alert(`Error verifying ${name}: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
  
  // Store verification result for the verification tab
  if (result.success) {
    verificationStatus[`${manager}-${name}`] = result.result;
  }
}

async function verifyPackageForTab(manager, name) {
  try {
    const response = await fetch('/api/verify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({manager, name})
    });
    
    const result = await response.json();
    
    if (result.success) {
      verificationStatus[`${manager}-${name}`] = result.result;
      return result.result;
    } else {
      verificationStatus[`${manager}-${name}`] = {status: 'error', message: result.message};
      return {status: 'error', message: result.message};
    }
  } catch (e) {
    verificationStatus[`${manager}-${name}`] = {status: 'error', message: e.message};
    return {status: 'error', message: e.message};
  }
}

async function verifyAllPackages() {
  const btn = document.getElementById('verifyAllBtn');
  if (!btn) return;
  
  btn.textContent = 'Verifying...';
  btn.disabled = true;
  
  try {
    // Verify packages in batches to avoid overwhelming the server
    const packages = data.filter(pkg => !verificationStatus[`${pkg.manager}-${pkg.name}`]);
    const batchSize = 5;
    
    for (let i = 0; i < packages.length; i += batchSize) {
      const batch = packages.slice(i, i + batchSize);
      const promises = batch.map(pkg => verifyPackageForTab(pkg.manager, pkg.name));
      await Promise.all(promises);
      
      // Update progress
      const progress = Math.min(100, ((i + batchSize) / packages.length) * 100);
      btn.textContent = `Verifying... ${Math.round(progress)}%`;
      
      // Small delay between batches
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    btn.textContent = '🔍 Verify All';
    renderVerification();
  } catch (e) {
    btn.textContent = '🔍 Verify All';
    alert(`Error verifying packages: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

function getVerificationStatus(manager, name) {
  const key = `${manager}-${name}`;
  const status = verificationStatus[key];
  if (status) {
    return {
      status: status.status,
      message: status.message,
      verified_at: status.verified_at
    };
  }
  return {status: 'unverified', message: 'Not verified yet'};
}

function getStatusIcon(status) {
  switch (status) {
    case 'verified': return '✅';
    case 'failed': return '❌';
    case 'unknown': return '❓';
    case 'error': return '⚠️';
    default: return '⏳';
  }
}

function getStatusClass(status) {
  switch (status) {
    case 'verified': return 'verified';
    case 'failed': return 'failed';
    case 'unknown': return 'unknown';
    case 'error': return 'failed';
    default: return 'unknown';
  }
}

function renderVerification() {
  const searchInput = document.getElementById('verificationSearch');
  const filterSelect = document.getElementById('verificationFilter');
  const tbody = document.querySelector('#verificationTable tbody');
  const count = document.getElementById('verificationCount');
  const totalSizeEl = document.getElementById('verificationTotalSize');
  
  const searchTerm = searchInput.value.trim().toLowerCase();
  const filterStatus = filterSelect.value;
  
  const filtered = data.filter(item => {
    const status = getVerificationStatus(item.manager, item.name);
    
    // Apply search filter
    if (searchTerm) {
      const matches = item.name.toLowerCase().includes(searchTerm) ||
                     item.manager.toLowerCase().includes(searchTerm) ||
                     status.message.toLowerCase().includes(searchTerm);
      if (!matches) return false;
    }
    
    // Apply status filter
    if (filterStatus && status.status !== filterStatus) return false;
    
    return true;
  });
  
  tbody.innerHTML = "";
  for (const item of filtered) {
    const status = getVerificationStatus(item.manager, item.name);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="pill">${esc(item.manager)}</span></td>
      <td>${esc(item.name)}</td>
      <td>${esc(item.version)}</td>
      <td class="size-cell">${esc(item.size_formatted || "0 B")}</td>
      <td>
        <span class="verify-btn ${getStatusClass(status.status)}">
          ${getStatusIcon(status.status)} ${status.status}
        </span>
      </td>
      <td class="muted">${esc(status.message)}</td>
      <td>
        <button class="verify-btn" onclick="verifyPackageForTab('${esc(item.manager)}', '${esc(item.name)}').then(() => renderVerification())">
          Verify
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  }
  
  count.textContent = `${filtered.length} / ${data.length} packages`;
  const totalSize = calculateTotalSize(filtered);
  totalSizeEl.textContent = `Total size: ${formatSize(totalSize)}`;
}

async function uninstallPackage(manager, name) {
  if (!confirm(`Are you sure you want to uninstall ${name}?`)) {
    return;
  }
  
  try {
    const response = await fetch('/api/uninstall', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({manager, name})
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(`Successfully uninstalled ${name}`);
      // Refresh data
      await loadData();
      renderPackages();
    } else {
      alert(`Failed to uninstall ${name}: ${result.message}`);
    }
  } catch (e) {
    alert(`Error uninstalling ${name}: ${e.message}`);
  }
}

function populateManagerDropdown() {
  const mgrSel = document.getElementById('mgr');
  const currentValue = mgrSel.value; // Preserve current selection
  
  mgrSel.innerHTML = '<option value="">All managers</option>';
  const managers = Array.from(new Set(data.map(d => d.manager))).sort();
  for (const m of managers) {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    mgrSel.appendChild(opt);
  }
  
  // Restore selection if it still exists
  if (currentValue && managers.includes(currentValue)) {
    mgrSel.value = currentValue;
  }
}

function renderPackages() {
  const mgrSel = document.getElementById('mgr');
  const q = document.getElementById('q');
  const tbody = document.querySelector('#tbl tbody');
  const count = document.getElementById('count');
  const totalSizeEl = document.getElementById('totalSize');

  // Only populate dropdown if it's empty or data has changed
  if (mgrSel.options.length <= 1) {
    populateManagerDropdown();
  }

  let state = { q: q.value.trim(), mgr: mgrSel.value };

  function matches(row){
    if (state.mgr && row.manager !== state.mgr) return false;
    if (!state.q) return true;
    const needle = state.q.toLowerCase();
    return (row.name||"").toLowerCase().includes(needle)
        || (row.version||"").toLowerCase().includes(needle)
        || (row.source||"").toLowerCase().includes(needle)
        || (row.path||"").toLowerCase().includes(needle)
        || (row.manager||"").toLowerCase().includes(needle);
  }

  tbody.innerHTML = "";
  const filtered = data.filter(matches);
  
  for (const r of filtered){
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="pill">${esc(r.manager||"")}</span></td>
      <td>${esc(r.name||"")}</td>
      <td>${esc(r.version||"")}</td>
      <td class="size-cell">${esc(r.size_formatted||"0 B")}</td>
      <td class="muted">${esc(r.path||"")}</td>
      <td class="muted">${esc(r.source||"")}</td>
      <td>
        <button class="uninstall-btn" onclick="uninstallPackage('${esc(r.manager)}', '${esc(r.name)}')">
          Uninstall
        </button>
        <button class="verify-btn" onclick="verifyPackage('${esc(r.manager)}', '${esc(r.name)}')" id="verify-${esc(r.manager)}-${esc(r.name)}">
          Verify
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  }
  
  count.textContent = `${filtered.length} / ${data.length} packages`;
  const totalSize = calculateTotalSize(filtered);
  totalSizeEl.textContent = `Total size: ${formatSize(totalSize)}`;
}

function renderHistory() {
  const searchInput = document.getElementById('historySearch');
  const sourceFilter = document.getElementById('historySourceFilter');
  const tbody = document.querySelector('#historyTable tbody');
  const count = document.getElementById('historyCount');
  
  const searchTerm = searchInput.value.trim().toLowerCase();
  const sourceFilterValue = sourceFilter.value;
  
  const filtered = history.filter(item => {
    // Apply search filter
    if (searchTerm) {
      const matches = item.name.toLowerCase().includes(searchTerm) ||
                     item.manager.toLowerCase().includes(searchTerm) ||
                     (item.source || '').toLowerCase().includes(searchTerm);
      if (!matches) return false;
    }
    
    // Apply source filter
    if (sourceFilterValue && item.source !== sourceFilterValue) return false;
    
    return true;
  });
  
  tbody.innerHTML = "";
  for (const item of filtered) {
    const sourceIcon = item.source === 'dashboard_uninstall' ? '🖥️' : '🔍';
    const sourceText = item.source === 'dashboard_uninstall' ? 'Dashboard' : 'Detected';
    
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${esc(item.name)}</td>
      <td>${esc(item.version)}</td>
      <td><span class="pill">${esc(item.manager)}</span></td>
      <td class="size-cell">${formatSize(item.size || 0)}</td>
      <td><span class="pill">${sourceIcon} ${sourceText}</span></td>
      <td class="muted">${formatDate(item.uninstalled_at)}</td>
    `;
    tbody.appendChild(tr);
  }
  
  count.textContent = `${filtered.length} / ${history.length} entries`;
}

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    
    tab.classList.add('active');
    const tabId = tab.dataset.tab + '-tab';
    document.getElementById(tabId).classList.add('active');
  });
});

// Event listeners
document.getElementById('q').addEventListener('input', renderPackages);
document.getElementById('mgr').addEventListener('change', renderPackages);
document.getElementById('historySearch').addEventListener('input', renderHistory);
document.getElementById('historySourceFilter').addEventListener('change', renderHistory);
document.getElementById('verificationSearch').addEventListener('input', renderVerification);
document.getElementById('verificationFilter').addEventListener('change', renderVerification);

document.getElementById('refreshBtn').addEventListener('click', async () => {
  await loadData();
  populateManagerDropdown(); // Refresh dropdown options
  renderPackages();
});

document.getElementById('clearHistory').addEventListener('click', async () => {
  if (confirm('Are you sure you want to clear all uninstall history?')) {
    try {
      await fetch('/api/clear-history', {method: 'POST'});
      await loadHistory();
      renderHistory();
    } catch (e) {
      alert('Failed to clear history: ' + e.message);
    }
  }
});

document.getElementById('verifyAllBtn').addEventListener('click', verifyAllPackages);
document.getElementById('refreshVerification').addEventListener('click', renderVerification);

document.getElementById('detectMissingBtn').addEventListener('click', async () => {
  const btn = document.getElementById('detectMissingBtn');
  btn.textContent = 'Detecting...';
  btn.disabled = true;
  
  try {
    const response = await fetch('/api/detect-missing', {method: 'POST'});
    const result = await response.json();
    
    if (result.success) {
      if (result.missing_count > 0) {
        alert(`Detected ${result.missing_count} packages that were uninstalled outside the dashboard!`);
        await loadHistory();
        renderHistory();
      } else {
        alert('No missing packages detected.');
      }
    } else {
      alert(`Failed to detect missing packages: ${result.message}`);
    }
  } catch (e) {
    alert(`Error detecting missing packages: ${e.message}`);
  } finally {
    btn.textContent = '🔍 Detect Missing';
    btn.disabled = false;
  }
});

// Conflicts handling
let conflicts = [];

async function loadConflicts() {
  try {
    const response = await fetch('/api/conflicts');
    const result = await response.json();
    if (result.success) {
      conflicts = result.conflicts;
    } else {
      conflicts = [];
    }
  } catch (e) {
    console.error('Failed to load conflicts:', e);
    conflicts = [];
  }
}

function renderConflicts() {
  const conflictsList = document.getElementById('conflictsList');
  const count = document.getElementById('conflictsCount');
  
  if (conflicts.length === 0) {
    conflictsList.innerHTML = '<div class="muted" style="text-align:center;padding:40px;">No conflicts detected! 🎉</div>';
    count.textContent = '0 conflicts';
    return;
  }
  
  conflictsList.innerHTML = '';
  for (const conflict of conflicts) {
    const div = document.createElement('div');
    div.className = `conflict-item ${conflict.severity}`;
    
    let packagesHtml = '';
    if (conflict.packages) {
      packagesHtml = '<div style="margin-top:8px;"><strong>Packages:</strong><ul style="margin:4px 0;padding-left:20px;">';
      for (const pkg of conflict.packages) {
        packagesHtml += `<li>${pkg.name} (${pkg.manager}) - ${pkg.version}</li>`;
      }
      packagesHtml += '</ul></div>';
    }
    
    let detailsHtml = '';
    if (conflict.details) {
      detailsHtml = `<div style="margin-top:8px;"><strong>Details:</strong><pre style="background:var(--bg);padding:8px;border-radius:4px;font-size:.85rem;overflow:auto;">${esc(conflict.details)}</pre></div>`;
    }
    
    div.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:start;">
        <div>
          <h4 style="margin:0 0 4px 0;">${esc(conflict.title)}</h4>
          <p style="margin:0;color:var(--muted);">${esc(conflict.description)}</p>
          ${packagesHtml}
          ${detailsHtml}
          <div style="margin-top:8px;"><strong>Suggestion:</strong> ${esc(conflict.suggestion)}</div>
        </div>
        <span class="severity-badge ${conflict.severity}">${conflict.severity}</span>
      </div>
    `;
    
    conflictsList.appendChild(div);
  }
  
  count.textContent = `${conflicts.length} conflicts found`;
}

document.getElementById('scanConflicts').addEventListener('click', async () => {
  await loadConflicts();
  renderConflicts();
});

document.getElementById('refreshConflicts').addEventListener('click', async () => {
  await loadConflicts();
  renderConflicts();
});

// CSV export
document.getElementById('exportCsv').addEventListener('click', ()=>{
  const state = { 
    q: document.getElementById('q').value.trim(), 
    mgr: document.getElementById('mgr').value 
  };
  
  function matches(row){
    if (state.mgr && row.manager !== state.mgr) return false;
    if (!state.q) return true;
    const needle = state.q.toLowerCase();
    return (row.name||"").toLowerCase().includes(needle)
        || (row.version||"").toLowerCase().includes(needle)
        || (row.source||"").toLowerCase().includes(needle)
        || (row.path||"").toLowerCase().includes(needle)
        || (row.manager||"").toLowerCase().includes(needle);
  }
  
  const rows = data.filter(matches);
  const cols = ["manager","name","version","size_formatted","path","source"];
  let csv = cols.join(",") + "\\n";
  for (const r of rows){
    csv += cols.map(c => `"${String(r[c]||"").replace(/"/g,'""')}"`).join(",") + "\\n";
  }
  const blob = new Blob([csv], {type:"text/csv"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = "packages.csv";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
});

// basic sort on header click
let sortKey = "name", sortDir = 1;
document.querySelectorAll('th[data-k]').forEach(th => {
  th.style.cursor = 'pointer';
  th.addEventListener('click', () => {
    const k = th.dataset.k;
    if (k === sortKey) sortDir *= -1; else { sortKey = k; sortDir = 1; }
    data.sort((a,b)=>{
      const va = (a[sortKey]||"").toLowerCase();
      const vb = (b[sortKey]||"").toLowerCase();
      if (va < vb) return -1*sortDir;
      if (va > vb) return 1*sortDir;
      return 0;
    });
    renderPackages();
  });
});

// Initialize
(async function(){
  await loadData();
  await loadHistory();
  await loadVerificationStatus();
  await loadConflicts();
  renderPackages();
  renderHistory();
  renderConflicts();
  renderVerification();
})();
</script>
</body>
</html>
"""

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        """Handle API requests."""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/uninstall':
            self.handle_uninstall()
        elif parsed_path.path == '/api/clear-history':
            self.handle_clear_history()
        elif parsed_path.path == '/api/verify':
            self.handle_verify()
        elif parsed_path.path == '/api/conflicts':
            self.handle_conflicts()
        elif parsed_path.path == '/api/detect-missing':
            self.handle_detect_missing()
        elif parsed_path.path == '/api/verification-status':
            self.handle_verification_status()
        elif parsed_path.path == '/api/save-verification-status':
            self.handle_save_verification_status()
        else:
            self.send_error(404)
    
    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/conflicts':
            self.handle_conflicts()
        else:
            # Default to serving static files
            super().do_GET()
    
    def handle_uninstall(self):
        """Handle package uninstall request."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            manager = data.get('manager')
            name = data.get('name')
            
            if not manager or not name:
                self.send_json_response({"success": False, "message": "Missing manager or name"})
                return
            
            # Find the package in current data to get its info
            current_data = []
            try:
                if DATA_PATH.exists():
                    current_data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
            
            package_info = None
            for item in current_data:
                if item.get('manager') == manager and item.get('name') == name:
                    package_info = item
                    break
            
            # Perform uninstall
            result = uninstall_package(manager, name)
            
            if result["success"] and package_info:
                # Add to history
                add_to_uninstall_history(package_info)
            
            self.send_json_response(result)
            
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_clear_history(self):
        """Handle clear history request."""
        try:
            save_uninstall_history([])
            self.send_json_response({"success": True, "message": "History cleared"})
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_verify(self):
        """Handle package verification request."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            manager = data.get('manager')
            name = data.get('name')
            
            if not manager or not name:
                self.send_json_response({"success": False, "message": "Missing manager or name"})
                return
            
            result = verify_package_integrity(manager, name)
            self.send_json_response({"success": True, "result": result})
            
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_conflicts(self):
        """Handle package conflicts detection request."""
        try:
            conflicts = detect_package_conflicts()
            self.send_json_response({"success": True, "conflicts": conflicts})
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_detect_missing(self):
        """Handle missing packages detection request."""
        try:
            # Load current packages
            current_packages = []
            if DATA_PATH.exists():
                current_packages = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            
            # Detect missing packages
            missing_packages = detect_missing_packages(current_packages)
            
            # Add them to history
            add_missing_packages_to_history(missing_packages)
            
            self.send_json_response({
                "success": True, 
                "missing_count": len(missing_packages),
                "missing_packages": missing_packages
            })
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_verification_status(self):
        """Handle verification status request."""
        try:
            verification_data = load_verification_status()
            self.send_json_response({"success": True, "verification_status": verification_data})
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    
    def handle_save_verification_status(self):
        """Handle save verification status request."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            verification_data = json.loads(post_data.decode('utf-8'))
            
            save_verification_status(verification_data)
            self.send_json_response({"success": True, "message": "Verification status saved"})
        except Exception as e:
            self.send_json_response({"success": False, "message": f"Error: {str(e)}"})
    

    
    def send_json_response(self, data):
        """Send JSON response."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def log_message(self, *args, **kwargs):
        # keep console quiet
        pass

def serve_dir(directory: Path, port: int):
    os.chdir(str(directory))
    if port == 0:
        # find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="Open the dashboard in your default browser")
    ap.add_argument("--port", type=int, default=8008, help="Port to serve on (0 = auto-pick)")
    args = ap.parse_args()

    # 1) Collect
    items = collect_all()
    
    # 2) Detect missing packages before saving new data
    missing_packages = detect_missing_packages(items)
    if missing_packages:
        print(f"[!] Detected {len(missing_packages)} packages that were uninstalled outside the dashboard")
        add_missing_packages_to_history(missing_packages)
    
    # 3) Write assets
    DATA_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")
    HTML_PATH.write_text(HTML_TEMPLATE, encoding="utf-8")
    
    # Save current packages as snapshot for next comparison
    save_packages_snapshot(items)
    
    # Initialize history file if it doesn't exist
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("[]", encoding="utf-8")
    
    # Initialize verification status file if it doesn't exist
    if not VERIFICATION_STATUS_PATH.exists():
        VERIFICATION_STATUS_PATH.write_text("{}", encoding="utf-8")

    print(f"[+] Wrote data:   {DATA_PATH}")
    print(f"[+] Wrote HTML:   {HTML_PATH}")
    print(f"[+] History file: {HISTORY_PATH}")
    print(f"[+] Verification status: {VERIFICATION_STATUS_PATH}")
    if missing_packages:
        print(f"[+] Added {len(missing_packages)} missing packages to history")

    # 3) Serve locally
    httpd, port = serve_dir(OUT_DIR, args.port)
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"[+] Serving dashboard at {url}")

    if args.open:
        # Give the server a tick to start
        time.sleep(0.2)
        webbrowser.open(url)

    try:
        # keep process alive
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[!] Shutting down server...")
        httpd.shutdown()

if __name__ == "__main__":
    main()
