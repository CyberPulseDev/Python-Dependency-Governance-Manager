import sys
import os
import json
import csv
import threading
import queue
import subprocess
import shutil
import zipfile
import re
import platform
import shlex
import tkinter as tk
import importlib.util
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime, timezone, timedelta

# --- Compatibility Imports ---
try:
    import importlib.metadata as metadata
except ImportError:  # Python < 3.8
    import importlib_metadata as metadata

# --- Configuration & Constants ---
APP_TITLE = "Pip Package Manager"
INSTALLED_APPS_TITLE = "Installed Applications Manager"
SETUP_ASSISTANT_TITLE = "GitHub Project Setup Assistant"
PLUGIN_MANAGER_TITLE = "Plugin Manager"

INSTALLED_PROJECTS_FILE = "installed_projects.json"
SNAPSHOTS_FILE = "pip_snapshots.json"
PLUGIN_DIR = "plugins"
PLUGIN_CONFIG_FILE = os.path.join(PLUGIN_DIR, "plugins.json")
PLUGIN_API_VERSION = "1.0"
RECENT_DAYS = 7
APP_DATA_DIR = "governance_data"
AUDIT_LOG_FILE = os.path.join(APP_DATA_DIR, "audit_logs.jsonl")
POLICY_FILE = os.path.join(APP_DATA_DIR, "policies.json")
VULN_CACHE_FILE = os.path.join(APP_DATA_DIR, "vulnerability_cache.json")
PACKAGE_CACHE_FILE = os.path.join(APP_DATA_DIR, "package_metadata_cache.json")
APP_CENTER_STATE_FILE = os.path.join(APP_DATA_DIR, "application_center_state.json")

# --- Theme Definitions ---
# Enhanced palette for better visual hierarchy and modern look
THEME_COLORS = {
    "light": {
        "bg": "#f5f5f7", "fg": "#1d1d1f",
        "surface": "#ffffff", "surface_alt": "#f8fafc",
        "sidebar_bg": "#111827", "sidebar_fg": "#e5e7eb", "sidebar_active": "#2563eb",
        "muted": "#64748b", "accent": "#2563eb",
        "success": "#16a34a", "warning": "#d97706", "danger": "#dc2626", "info": "#0284c7",
        "text_bg": "#ffffff", "text_fg": "#1d1d1f",
        "tree_bg": "#ffffff", "tree_fg": "#1d1d1f",
        "tree_hdr_bg": "#e5e5ea", "tree_hdr_fg": "#000000",
        "select_bg": "#007aff", "select_fg": "#ffffff",
        "row_even": "#ffffff", "row_odd": "#f2f2f7",
        "border": "#d1d1d6",
        "health_good": "#34c759", "health_mod": "#ff9500", "health_bad": "#ff3b30",
        "btn_bg": "#e3e3e3"
    },
    "dark": {
        "bg": "#1c1c1e", "fg": "#f5f5f7",
        "surface": "#242428", "surface_alt": "#2c2c2e",
        "sidebar_bg": "#0f172a", "sidebar_fg": "#e2e8f0", "sidebar_active": "#3b82f6",
        "muted": "#94a3b8", "accent": "#60a5fa",
        "success": "#22c55e", "warning": "#f59e0b", "danger": "#ef4444", "info": "#38bdf8",
        "text_bg": "#2c2c2e", "text_fg": "#f5f5f7",
        "tree_bg": "#2c2c2e", "tree_fg": "#f5f5f7",
        "tree_hdr_bg": "#3a3a3c", "tree_hdr_fg": "#ffffff",
        "select_bg": "#0a84ff", "select_fg": "#ffffff",
        "row_even": "#2c2c2e", "row_odd": "#1c1c1e",
        "border": "#48484a",
        "health_good": "#30d158", "health_mod": "#ff9f0a", "health_bad": "#ff453a",
        "btn_bg": "#3a3a3c"
    }
}

# --- Helper Classes ---

class SubprocessHandler:
    @staticmethod
    def get_startup_flags():
        kwargs = {}
        if platform.system() == "Windows":
            # Use CREATE_NO_WINDOW (0x08000000) to hide console
            kwargs["creationflags"] = 0x08000000
        return kwargs

    @staticmethod
    def run_command(cmd_list, cwd=None, capture_output=False, env=None):
        try:
            kwargs = SubprocessHandler.get_startup_flags()
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            if capture_output:
                proc = subprocess.run(
                    cmd_list, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, env=run_env, **kwargs
                )
                return proc.returncode, proc.stdout, proc.stderr
            else:
                proc = subprocess.Popen(cmd_list, cwd=cwd, env=run_env, **kwargs)
                return proc
        except Exception as e:
            if capture_output:
                return -1, "", str(e)
            raise e

    @staticmethod
    def find_git():
        git_cmd = shutil.which("git")
        if git_cmd: return git_cmd
        if platform.system() == "Windows":
            potential_paths = [
                r"C:\Program Files\Git\cmd\git.exe",
                r"C:\Program Files\Git\bin\git.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
                os.path.expandvars(r"%ProgramFiles%\Git\cmd\git.exe"),
            ]
            for p in potential_paths:
                if os.path.exists(p): return p
        return None

class VenvHandler:
    @staticmethod
    def get_venv_python(project_path, venv_name=".venv"):
        if platform.system() == "Windows":
            return os.path.join(project_path, venv_name, "Scripts", "python.exe")
        else:
            return os.path.join(project_path, venv_name, "bin", "python")

    @staticmethod
    def is_venv_valid(project_path, venv_name=".venv"):
        exe = VenvHandler.get_venv_python(project_path, venv_name)
        return os.path.exists(exe) and os.path.isfile(exe)

    @staticmethod
    def detect_venv(project_path):
        common_names = [".venv", "venv", "env"]
        for name in common_names:
            if VenvHandler.is_venv_valid(project_path, name):
                return name
        return None

    @staticmethod
    def create_venv(project_path, venv_name=".venv"):
        cmd = [sys.executable, "-m", "venv", venv_name]
        rc, out, err = SubprocessHandler.run_command(cmd, cwd=project_path, capture_output=True)
        return rc == 0, err

class SnapshotManager:
    def __init__(self):
        self.filepath = SNAPSHOTS_FILE
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            self._save_data({"snapshots": []})

    def _load_data(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"snapshots": []}

    def _save_data(self, data):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def create_snapshot(self, interpreter_path, note=""):
        if not os.path.exists(interpreter_path):
            return False, f"Interpreter not found: {interpreter_path}"

        cmd = [interpreter_path, "-m", "pip", "freeze"]
        rc, out, err = SubprocessHandler.run_command(cmd, capture_output=True)
        if rc != 0:
            return False, f"pip freeze failed: {err}"

        packages = [line.strip() for line in out.splitlines() if line.strip() and not line.startswith("#")]
        
        try:
            norm_interp = os.path.normcase(os.path.realpath(interpreter_path))
            norm_sys = os.path.normcase(os.path.realpath(sys.executable))
            scope = "Global" if norm_interp == norm_sys else "Project/Venv"
        except:
            scope = "Unknown"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        snapshot_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(packages)}"
        
        snapshot = {
            "id": snapshot_id,
            "created_at": timestamp,
            "scope": scope,
            "python": interpreter_path,
            "packages": packages,
            "note": note
        }

        data = self._load_data()
        data["snapshots"].insert(0, snapshot)
        self._save_data(data)
        return True, snapshot

    def get_snapshots(self):
        return self._load_data().get("snapshots", [])

    def delete_snapshot(self, snapshot_id):
        data = self._load_data()
        data["snapshots"] = [s for s in data["snapshots"] if s["id"] != snapshot_id]
        self._save_data(data)

class RollbackEngine:
    @staticmethod
    def restore_snapshot(snapshot, status_callback):
        interpreter = snapshot.get("python")
        if not os.path.exists(interpreter):
             status_callback(f"Error: Target interpreter {interpreter} not found. Cannot rollback.")
             return False

        packages = snapshot.get("packages", [])
        if not packages:
            status_callback("Snapshot is empty. Nothing to restore.")
            return True

        status_callback(f"Initiating rollback for {len(packages)} packages...")
        req_filename = f"rollback_{snapshot['id']}.txt"
        req_path = os.path.abspath(req_filename)
        
        try:
            with open(req_path, "w", encoding="utf-8") as f:
                f.write("\n".join(packages))
            
            cmd = [interpreter, "-m", "pip", "install", "-r", req_filename]
            status_callback(f"Running restoration command...")
            rc, out, err = SubprocessHandler.run_command(cmd, capture_output=True)
            
            if rc == 0:
                status_callback("Rollback successful. Environment restored.")
                return True
            else:
                status_callback(f"Rollback FAILED. Output:\n{err}")
                return False

        except Exception as e:
            status_callback(f"Critical error during rollback: {e}")
            return False
        finally:
            if os.path.exists(req_path):
                os.remove(req_path)

class HealthEngine:
    SCORE_STALE = 2
    SCORE_DEPTH = 3
    SCORE_SIZE = 2
    SCORE_HOOKS = 2
    THRESH_STALE_DAYS = 730
    THRESH_SIZE_MB = 100
    THRESH_DEPTH = 10

    @staticmethod
    def analyze_all(packages_map):
        graph = {name: pkg.requires_simple for name, pkg in packages_map.items()}
        depth_cache = {}

        def get_depth(name, visited):
            if name in depth_cache: return depth_cache[name]
            if name in visited: return 0
            deps = graph.get(name, [])
            if not deps:
                depth_cache[name] = 0
                return 0
            visited.add(name)
            max_d = 0
            for dep in deps:
                clean_dep = dep.split('[')[0].split(';')[0].split(' ')[0].split('=')[0].split('>')[0].split('<')[0]
                max_d = max(max_d, get_depth(clean_dep, visited))
            visited.remove(name)
            depth_cache[name] = 1 + max_d
            return 1 + max_d

        for name, pkg in packages_map.items():
            score = 0
            reasons = []

            if pkg.latest_mtime:
                age = datetime.now(timezone.utc) - pkg.latest_mtime
                if age.days > HealthEngine.THRESH_STALE_DAYS:
                    score += HealthEngine.SCORE_STALE
                    reasons.append(f"Stale: No updates in {age.days // 30} months")

            if pkg.size_mb > HealthEngine.THRESH_SIZE_MB:
                score += HealthEngine.SCORE_SIZE
                reasons.append(f"Large Footprint: {pkg.size_mb:.1f} MB")

            if pkg.has_entry_points:
                score += HealthEngine.SCORE_HOOKS
                reasons.append("Executables: Contains entry points")

            depth = get_depth(name, set())
            if depth > HealthEngine.THRESH_DEPTH:
                score += HealthEngine.SCORE_DEPTH
                reasons.append(f"Deep Chain: {depth} dependency levels")

            pkg.health_score = score
            pkg.health_reasons = reasons
            
            if score == 0:
                pkg.health_status = "Healthy"
                pkg.health_color = "health_good"
                pkg.health_badge = "🟢"
            elif score <= 5:
                pkg.health_status = "Moderate Risk"
                pkg.health_color = "health_mod"
                pkg.health_badge = "🟡"
            else:
                pkg.health_status = "High Risk"
                pkg.health_color = "health_bad"
                pkg.health_badge = "🔴"

class PackageInfo:
    def __init__(self, name, version, summary, location, size_bytes, latest_mtime, requires, metadata_text, has_entry_points=False):
        self.name = name
        self.version = version
        self.summary = summary or "No summary available"
        self.location = location
        self.size_bytes = size_bytes
        self.latest_mtime = latest_mtime
        self.requires = requires or []
        self.requires_simple = [r.split(';')[0].split('(')[0].split('[')[0].strip() for r in (requires or [])]
        self.metadata_text = metadata_text or ""
        self.outdated = False
        self.latest_version = None
        self.has_entry_points = has_entry_points
        self.health_score = 0
        self.health_status = "Analyzing..."
        self.health_reasons = []
        self.health_color = "fg"
        self.health_badge = "⚪"

    @property
    def size_mb(self):
        return self.size_bytes / (1024 * 1024) if self.size_bytes else 0.0

    @property
    def is_recent(self):
        if not self.latest_mtime: return False
        now = datetime.now(timezone.utc)
        return (now - self.latest_mtime) <= timedelta(days=RECENT_DAYS)

class AuditLogger:
    def __init__(self, filepath=AUDIT_LOG_FILE):
        self.filepath = filepath
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)

    def log(self, action, details=None, status="ok"):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "status": status,
            "details": details or {}
        }
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=True) + "\n")
        except Exception:
            pass
        return record

    def read(self, limit=500, action_filter=None, status_filter=None):
        rows = []
        if not os.path.exists(self.filepath):
            return rows
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if action_filter and action_filter.lower() not in item.get("action", "").lower():
                        continue
                    if status_filter and status_filter != "All" and item.get("status") != status_filter:
                        continue
                    rows.append(item)
            return rows[-limit:][::-1]
        except Exception:
            return []

class OfflineCacheManager:
    def __init__(self):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        self.vuln_cache_file = VULN_CACHE_FILE
        self.package_cache_file = PACKAGE_CACHE_FILE
        self._ensure_defaults()

    def _ensure_defaults(self):
        if not os.path.exists(self.vuln_cache_file):
            with open(self.vuln_cache_file, "w", encoding="utf-8") as f:
                json.dump({"updated_at": None, "vulnerabilities": []}, f, indent=2)
        if not os.path.exists(self.package_cache_file):
            with open(self.package_cache_file, "w", encoding="utf-8") as f:
                json.dump({"updated_at": None, "packages": {}}, f, indent=2)

    def load_vulnerabilities(self):
        try:
            with open(self.vuln_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("vulnerabilities", []), data.get("updated_at")
        except Exception:
            return [], None

    def save_package_metadata(self, packages):
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "packages": {
                p.name.lower(): {
                    "name": p.name, "version": p.version, "license": LicenseScanner.extract_license(p),
                    "summary": p.summary, "requires": p.requires_simple
                } for p in packages
            }
        }
        try:
            with open(self.package_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

class SecurityScanner:
    HIGH_SEVERITIES = {"critical", "high"}

    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
        self.results = []
        self.cache_updated_at = None

    @staticmethod
    def _version_matches(current, spec):
        if not spec:
            return True
        spec = str(spec).strip()
        try:
            from packaging.version import Version
            cur = Version(current)
            for part in [x.strip() for x in spec.split(",") if x.strip()]:
                if part.startswith("<=") and not cur <= Version(part[2:].strip()): return False
                if part.startswith(">=") and not cur >= Version(part[2:].strip()): return False
                if part.startswith("==") and not cur == Version(part[2:].strip()): return False
                if part.startswith("<") and not cur < Version(part[1:].strip()): return False
                if part.startswith(">") and not cur > Version(part[1:].strip()): return False
        except Exception:
            return spec in current
        return True

    def scan(self, packages_map):
        vulnerabilities, self.cache_updated_at = self.cache_manager.load_vulnerabilities()
        findings = []
        for vuln in vulnerabilities:
            name = str(vuln.get("package", vuln.get("name", ""))).lower()
            pkg = packages_map.get(name) or packages_map.get(vuln.get("package", ""))
            if not pkg:
                continue
            affected = vuln.get("affected_versions") or vuln.get("version_spec") or vuln.get("specifier")
            if self._version_matches(pkg.version, affected):
                findings.append({
                    "package": pkg.name,
                    "version": pkg.version,
                    "id": vuln.get("id", vuln.get("vulnerability_id", "LOCAL-CACHE")),
                    "severity": vuln.get("severity", "Unknown"),
                    "summary": vuln.get("summary", "Cached vulnerability match"),
                    "recommendation": vuln.get("recommendation", "Review package and upgrade when a safe version is available.")
                })
        self.results = findings
        return findings

class LicenseScanner:
    RISKY_LICENSES = {"gpl", "agpl", "lgpl", "unknown", "proprietary"}

    @staticmethod
    def extract_license(pkg):
        for line in pkg.metadata_text.splitlines():
            if line.lower().startswith("license:"):
                value = line.split(":", 1)[1].strip()
                return value or "Unknown"
            if line.lower().startswith("classifier: license"):
                return line.split("::")[-1].strip() or "Unknown"
        return "Unknown"

    def scan(self, packages_map, blocked=None):
        blocked = {b.lower() for b in (blocked or [])}
        findings = []
        for pkg in packages_map.values():
            lic = self.extract_license(pkg)
            lic_lower = lic.lower()
            status = "Pass"
            if lic_lower == "unknown":
                status = "Unknown"
            if any(token in lic_lower for token in self.RISKY_LICENSES) or any(b in lic_lower for b in blocked):
                status = "Review"
            findings.append({"package": pkg.name, "version": pkg.version, "license": lic, "status": status})
        return findings

class PolicyEngine:
    DEFAULT_POLICIES = [
        {"id": "no_unpinned_dependencies", "name": "No unpinned dependencies", "enabled": True, "type": "requirements_pinned"},
        {"id": "block_high_vulnerabilities", "name": "Block high severity vulnerabilities", "enabled": True, "type": "vulnerability_severity", "severity": "high"},
        {"id": "block_gpl_licenses", "name": "Block GPL licenses", "enabled": False, "type": "blocked_license", "licenses": ["GPL", "AGPL"]},
        {"id": "require_virtual_environment", "name": "Require virtual environment usage", "enabled": False, "type": "require_venv"}
    ]

    def __init__(self, filepath=POLICY_FILE):
        self.filepath = filepath
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            self.save(self.DEFAULT_POLICIES)

    def load(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f).get("policies", self.DEFAULT_POLICIES)
        except Exception:
            return list(self.DEFAULT_POLICIES)

    def save(self, policies):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump({"policies": policies}, f, indent=2)

    def evaluate(self, packages_map, vulnerabilities=None, license_findings=None, requirements_findings=None):
        results = []
        vulnerabilities = vulnerabilities or []
        license_findings = license_findings or []
        requirements_findings = requirements_findings or []
        for policy in self.load():
            if not policy.get("enabled", True):
                results.append({"policy": policy.get("name"), "status": "Disabled", "details": ""})
                continue
            ptype = policy.get("type")
            status, details = "Pass", ""
            if ptype == "vulnerability_severity":
                threshold = str(policy.get("severity", "high")).lower()
                hits = [v for v in vulnerabilities if str(v.get("severity", "")).lower() in ("critical", "high") or str(v.get("severity", "")).lower() == threshold]
                if hits:
                    status, details = "Fail", f"{len(hits)} vulnerable packages exceed policy."
            elif ptype == "blocked_license":
                blocked = [x.lower() for x in policy.get("licenses", [])]
                hits = [l for l in license_findings if any(b in l.get("license", "").lower() for b in blocked)]
                if hits:
                    status, details = "Fail", f"{len(hits)} packages use blocked licenses."
            elif ptype == "requirements_pinned":
                hits = [r for r in requirements_findings if r.get("issue") == "Unpinned"]
                if hits:
                    status, details = "Fail", f"{len(hits)} requirement entries are unpinned."
            elif ptype == "require_venv":
                if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
                    status, details = "Fail", "Current interpreter is not a virtual environment."
            results.append({"policy": policy.get("name"), "status": status, "details": details})
        return results

class RequirementsAuditor:
    FILES = ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg")

    def find_requirement_files(self, root):
        found = []
        if not root or not os.path.isdir(root):
            return found
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "venv", "__pycache__", "node_modules")]
            for name in self.FILES:
                if name in files:
                    found.append(os.path.join(base, name))
            if len(found) > 40:
                break
        return found

    def parse_requirements_txt(self, path):
        reqs = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw or raw.startswith("#") or raw.startswith("-"):
                        continue
                    name = re.split(r"[<>=!~\[]", raw, maxsplit=1)[0].strip()
                    if name:
                        reqs[name.lower()] = raw
        except Exception:
            pass
        return reqs

    def audit(self, root, packages_map):
        files = self.find_requirement_files(root)
        declared = {}
        for path in files:
            if os.path.basename(path) == "requirements.txt":
                declared.update(self.parse_requirements_txt(path))
        installed = {name.lower(): pkg for name, pkg in packages_map.items()}
        findings = []
        for name, spec in declared.items():
            if name not in installed:
                findings.append({"package": name, "issue": "Missing", "declared": spec, "installed": ""})
            elif not any(op in spec for op in ("==", "~=", ">=", "<=", ">", "<")):
                findings.append({"package": name, "issue": "Unpinned", "declared": spec, "installed": installed[name].version})
        for name, pkg in installed.items():
            if declared and name not in declared:
                findings.append({"package": pkg.name, "issue": "Extra", "declared": "", "installed": pkg.version})
            if pkg.outdated:
                findings.append({"package": pkg.name, "issue": "Outdated", "declared": declared.get(name, ""), "installed": pkg.version})
        return files, findings

class EnvironmentComparator:
    @staticmethod
    def packages_from_snapshot(snapshot):
        packages = {}
        for item in snapshot.get("packages", []):
            if "==" in item:
                name, version = item.split("==", 1)
                packages[name.lower()] = version
        return packages

    @staticmethod
    def compare(left, right):
        rows = []
        all_names = sorted(set(left) | set(right))
        for name in all_names:
            lv, rv = left.get(name), right.get(name)
            if lv and not rv:
                state = "Removed"
            elif rv and not lv:
                state = "Added"
            elif lv != rv:
                state = "Changed"
            else:
                state = "Same"
            if state != "Same":
                rows.append({"package": name, "left": lv or "", "right": rv or "", "change": state})
        return rows

class SupplyChainGraphBuilder:
    def build_edges(self, packages_map):
        edges = []
        installed = {k.lower(): v for k, v in packages_map.items()}
        for pkg in packages_map.values():
            for dep in pkg.requires_simple:
                dep_name = dep.lower()
                edges.append({
                    "source": pkg.name,
                    "target": dep,
                    "installed": dep_name in installed,
                    "risk": pkg.health_status
                })
        return edges

class DashboardController:
    def __init__(self):
        self.last_scan_time = None

    def kpis(self, packages_map, vulnerabilities, license_findings, policy_results):
        high_risk = [p for p in packages_map.values() if p.health_status == "High Risk"]
        license_issues = [l for l in license_findings if l.get("status") in ("Review", "Unknown")]
        policy_violations = [p for p in policy_results if p.get("status") == "Fail"]
        return {
            "Total packages": len(packages_map),
            "Outdated packages": len([p for p in packages_map.values() if p.outdated]),
            "High-risk packages": len(high_risk),
            "Vulnerable packages": len({v.get("package") for v in vulnerabilities}),
            "License issues": len(license_issues),
            "Policy violations": len(policy_violations),
            "Last scan time": self.last_scan_time or "Not scanned"
        }

# --- Plugin Architecture ---

class PluginContext:
    def __init__(self, app_instance, plugin_id=None, permissions=None):
        self._app = app_instance
        self.plugin_id = plugin_id or "unknown"
        self.permissions = set(permissions or [])

    def has_permission(self, permission):
        return permission in self.permissions or "app:read" in self.permissions

    def log(self, message):
        self._app.command_queue.put(("plugin_log", {"plugin_id": self.plugin_id, "message": str(message)}))

    def add_tab(self, title, widget_factory):
        if not self.has_permission("ui:extend"):
            self.log("Denied add_tab: missing ui:extend permission.")
            return
        try:
            frame = ttk.Frame(self._app.detail_notebook if hasattr(self._app, "detail_notebook") else self._app)
            widget = widget_factory(frame)
            widget.pack(fill=tk.BOTH, expand=True)
            self._app.detail_notebook.add(frame, text=title)
        except Exception as e:
            self.log(f"Plugin failed to add tab: {e}")

    def add_menu_command(self, label, command):
        if not self.has_permission("ui:extend"):
            self.log("Denied add_menu_command: missing ui:extend permission.")
            return
        try:
            self._app.plugin_menu.add_command(label=label, command=command)
        except Exception as e:
            self.log(f"Plugin failed to add menu: {e}")

    def get_packages_snapshot(self):
        if not self.has_permission("packages:read"):
            self.log("Denied package snapshot: missing packages:read permission.")
            return []
        return [{"name": p.name, "version": p.version, "outdated": p.outdated, "health": p.health_status} for p in self._app.all_packages.values()]

    def get_policy_results(self):
        if not self.has_permission("policies:read"):
            self.log("Denied policy results: missing policies:read permission.")
            return []
        return list(getattr(self._app, "policy_results", []))

class PluginBase:
    def on_load(self, context): pass
    def on_unload(self, context): pass
    def on_packages_loaded(self, context, packages): pass
    def on_scan_requested(self, context): pass
    def on_policy_check(self, context, results): pass
    def on_export(self, context, path, fmt): pass

class PluginSandbox:
    def __init__(self, manager, meta):
        self.manager = manager
        self.meta = meta
        self.plugin_id = meta.get("id", "unknown")
        self.instance = None
        self.status = "Discovered"
        self.health = "Unknown"
        self.errors = []

    def context(self):
        return PluginContext(self.manager.app, self.plugin_id, self.meta.get("permissions", []))

    def record_error(self, hook, exc):
        message = f"{hook}: {exc}"
        self.errors.append({"timestamp": datetime.now(timezone.utc).isoformat(), "message": message})
        self.status = "Error"
        self.health = "Unhealthy"
        self.manager.log_plugin(self.plugin_id, message, "error")

    def load(self):
        try:
            entry_file = os.path.join(self.meta["dir_path"], self.meta.get("entry", "plugin.py"))
            spec = importlib.util.spec_from_file_location(f"plugin_{self.plugin_id.replace('.', '_')}", entry_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "Plugin"):
                raise RuntimeError("plugin.py must expose a Plugin class")
            self.instance = module.Plugin()
            self.status = "Loaded"
            self.health = "Healthy"
            self.call("on_load")
            return True
        except Exception as e:
            self.record_error("load", e)
            return False

    def unload(self):
        self.call("on_unload")
        self.instance = None
        self.status = "Disabled"

    def call(self, hook, *args):
        if not self.instance or not hasattr(self.instance, hook):
            return None
        try:
            return getattr(self.instance, hook)(self.context(), *args)
        except Exception as e:
            self.record_error(hook, e)
            return None

class PluginRegistry:
    REQUIRED_FIELDS = ("id", "name", "version", "author", "description", "category", "permissions", "api_version")

    def __init__(self, plugin_dir=PLUGIN_DIR):
        self.plugin_dir = plugin_dir

    def discover(self):
        discovered = []
        if not os.path.exists(self.plugin_dir):
            return discovered
        for d in os.listdir(self.plugin_dir):
            path = os.path.join(self.plugin_dir, d)
            man_path = os.path.join(path, "manifest.json")
            if not os.path.isdir(path) or not os.path.exists(man_path):
                continue
            try:
                with open(man_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta.setdefault("entry", "plugin.py")
                meta.setdefault("category", "General")
                meta.setdefault("permissions", ["packages:read"])
                meta.setdefault("enabled", False)
                missing = [field for field in self.REQUIRED_FIELDS if field not in meta]
                if missing:
                    meta["manifest_warning"] = f"Missing fields: {', '.join(missing)}"
                if meta.get("api_version") != PLUGIN_API_VERSION:
                    meta["manifest_warning"] = f"Unsupported API version {meta.get('api_version')}"
                meta["dir_path"] = path
                discovered.append(meta)
            except Exception as e:
                discovered.append({
                    "id": d, "name": d, "version": "", "author": "", "description": str(e),
                    "category": "Invalid", "permissions": [], "api_version": "", "dir_path": path,
                    "manifest_warning": str(e)
                })
        return discovered

class PluginManager:
    def __init__(self, app_instance):
        self.app = app_instance
        self.plugins = {}
        self.config = self._load_config()
        self.logs = []
        self.registry = PluginRegistry()
        self._ensure_plugin_dir()

    def _ensure_plugin_dir(self):
        if not os.path.exists(PLUGIN_DIR):
            os.makedirs(PLUGIN_DIR)
            self._create_example_plugin()

    def _create_example_plugin(self):
        ex_dir = os.path.join(PLUGIN_DIR, "example_stats")
        os.makedirs(ex_dir, exist_ok=True)
        manifest = {
            "id": "example.plugin.stats", "name": "Package Statistics", "version": "1.0.0",
            "author": "System", "description": "Adds a tab showing package stats.",
            "category": "Reporting", "permissions": ["packages:read"],
            "api_version": PLUGIN_API_VERSION, "entry": "plugin.py", "enabled": False
        }
        with open(os.path.join(ex_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        code = """
import tkinter as tk
class Plugin:
    def on_load(self, context): context.log("Stats plugin loaded.")
    def on_packages_loaded(self, context, packages): context.log(f"Stats: {len(packages)} packages.")
"""
        with open(os.path.join(ex_dir, "plugin.py"), "w") as f:
            f.write(code)

    def _load_config(self):
        if os.path.exists(PLUGIN_CONFIG_FILE):
            try:
                with open(PLUGIN_CONFIG_FILE, "r", encoding="utf-8") as f: return json.load(f)
            except: pass
        return {"enabled": []}

    def save_config(self):
        os.makedirs(PLUGIN_DIR, exist_ok=True)
        with open(PLUGIN_CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(self.config, f, indent=2)

    def discover_plugins(self):
        enabled = set(self.config.get("enabled", []))
        discovered = self.registry.discover()
        for meta in discovered:
            meta["enabled"] = meta.get("id") in enabled
            sandbox = self.plugins.get(meta.get("id"))
            meta["status"] = sandbox.status if sandbox else ("Enabled" if meta["enabled"] else "Disabled")
            meta["health"] = sandbox.health if sandbox else ("Not loaded" if meta["enabled"] else "Disabled")
        return discovered

    def load_enabled_plugins(self):
        plugins = self.discover_plugins()
        enabled_ids = set(self.config.get("enabled", []))
        for meta in plugins:
            if meta["id"] in enabled_ids:
                self.load_plugin(meta)

    def load_plugin(self, meta):
        if meta.get("manifest_warning"):
            self.log_plugin(meta.get("id", "unknown"), meta["manifest_warning"], "warning")
        sandbox = PluginSandbox(self, meta)
        self.plugins[meta["id"]] = sandbox
        ok = sandbox.load()
        if not ok:
            self.toggle_plugin(meta["id"], False)
        return ok

    def toggle_plugin(self, plugin_id, enable=True):
        enabled = set(self.config.get("enabled", []))
        if enable:
            enabled.add(plugin_id)
        else:
            enabled.discard(plugin_id)
            sandbox = self.plugins.pop(plugin_id, None)
            if sandbox:
                sandbox.unload()
        self.config["enabled"] = list(enabled)
        self.save_config()
        self.app.audit_logger.log("plugin_enabled" if enable else "plugin_disabled", {"plugin_id": plugin_id})
        if enable:
            meta = next((p for p in self.registry.discover() if p.get("id") == plugin_id), None)
            if meta:
                self.load_plugin(meta)

    def reload_plugin(self, plugin_id):
        sandbox = self.plugins.pop(plugin_id, None)
        if sandbox:
            sandbox.unload()
        meta = next((p for p in self.registry.discover() if p.get("id") == plugin_id), None)
        if meta:
            self.load_plugin(meta)
            self.log_plugin(plugin_id, "Reloaded plugin.", "info")

    def log_plugin(self, plugin_id, message, level="info"):
        row = {"time": datetime.now().strftime("%H:%M:%S"), "plugin_id": plugin_id, "level": level, "message": str(message)}
        self.logs.append(row)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def notify_packages_loaded(self):
        pkgs = [{"name": p.name, "version": p.version, "outdated": p.outdated, "health": p.health_status} for p in self.app.all_packages.values()]
        for sandbox in list(self.plugins.values()):
            sandbox.call("on_packages_loaded", pkgs)

    def notify_scan_requested(self):
        for sandbox in list(self.plugins.values()):
            sandbox.call("on_scan_requested")

    def notify_policy_check(self, results):
        for sandbox in list(self.plugins.values()):
            sandbox.call("on_policy_check", results)

    def notify_export(self, path, fmt):
        for sandbox in list(self.plugins.values()):
            sandbox.call("on_export", path, fmt)

class PluginManagerWindow(tk.Toplevel):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.title(PLUGIN_MANAGER_TITLE)
        self.geometry("980x620")
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        # Header
        hdr = ttk.Frame(self, padding=15)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Plugin Registry", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(hdr, text=f"API {PLUGIN_API_VERSION}", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10)
        
        # List
        cols = ("name", "version", "category", "status", "health", "permissions")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.column("name", width=220)
        self.tree.heading("version", text="Version")
        self.tree.column("version", width=80)
        self.tree.heading("category", text="Category")
        self.tree.column("category", width=120)
        self.tree.heading("status", text="Status")
        self.tree.column("status", width=110)
        self.tree.heading("health", text="Health")
        self.tree.column("health", width=130)
        self.tree.heading("permissions", text="Permissions")
        self.tree.column("permissions", width=280)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        log_frame = ttk.LabelFrame(self, text="Plugin Logs", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        self.log_text = tk.Text(log_frame, height=8, wrap="word", relief="flat", font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Footer
        btn_frame = ttk.Frame(self, padding=15)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Enable / Disable", command=self.toggle_selection).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Reload", command=self.reload_selection).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        self.refresh()

    def _apply_theme(self):
        theme = self.master.current_theme if hasattr(self.master, 'current_theme') else "light"
        colors = THEME_COLORS.get(theme, THEME_COLORS["light"])
        self.configure(bg=colors["bg"])
        if hasattr(self, "log_text"):
            self.log_text.configure(bg=colors["text_bg"], fg=colors["text_fg"], insertbackground=colors["fg"])

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        plugins = self.manager.discover_plugins()
        for p in plugins:
            warning = f" ({p.get('manifest_warning')})" if p.get("manifest_warning") else ""
            self.tree.insert("", tk.END, iid=p["id"], values=(
                p.get("name", p["id"]),
                p.get("version", ""),
                p.get("category", "General"),
                p.get("status", "Disabled"),
                f"{p.get('health', 'Unknown')}{warning}",
                ", ".join(p.get("permissions", []))
            ))
        if hasattr(self, "log_text"):
            self.log_text.delete("1.0", tk.END)
            for row in self.manager.logs[-200:]:
                self.log_text.insert(tk.END, f"[{row['time']}] {row['level'].upper()} {row['plugin_id']}: {row['message']}\n")
        return
        enabled_ids = set(self.manager.config.get("enabled", []))
        plugins = self.manager.discover_plugins()
        for p in plugins:
            status = "🟢 Enabled" if p["id"] in enabled_ids else "⚪ Disabled"
            self.tree.insert("", tk.END, iid=p["id"], values=(p["name"], p["version"], status))

    def toggle_selection(self):
        sel = self.tree.selection()
        if not sel: return
        pid = sel[0]
        currently_enabled = pid in self.manager.config.get("enabled", [])
        self.manager.toggle_plugin(pid, not currently_enabled)
        self.refresh()

    def reload_selection(self):
        sel = self.tree.selection()
        if not sel: return
        self.manager.reload_plugin(sel[0])
        self.refresh()

# ---------------------------------------------------------
# Installed Applications Manager (Modernized)
# ---------------------------------------------------------
class InstalledAppsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title(INSTALLED_APPS_TITLE)
        self.geometry("1000x600")
        self.projects_data = []
        self._init_data()
        self._build_ui()
        self._apply_theme()
        self._refresh_list()

    def _init_data(self):
        self.projects_data = []
        if os.path.exists(INSTALLED_PROJECTS_FILE):
            try:
                with open(INSTALLED_PROJECTS_FILE, "r", encoding="utf-8") as f:
                    self.projects_data = json.load(f)
            except: pass 

    def _save_data(self):
        try:
            with open(INSTALLED_PROJECTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.projects_data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _build_ui(self):
        # Toolbar
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Label(toolbar, text="Projects", font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Button(toolbar, text="▶ Run", command=self.run_app).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="📂 Open Folder", command=self.open_dir).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🗑 Remove", command=self.remove_entry).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🔄 Refresh", command=self._refresh_list).pack(side=tk.RIGHT, padx=5)

        # Split
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Tree
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)
        
        cols = ("name", "env_type", "path", "dep_count")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Application Name")
        self.tree.heading("env_type", text="Environment")
        self.tree.heading("path", text="Path")
        self.tree.heading("dep_count", text="Deps")
        self.tree.column("dep_count", width=60, anchor="center")
        
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.run_app())
        
        # Context Menu
        self.context_menu = tk.Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Run Application", command=self.run_app)
        self.context_menu.add_command(label="Open Directory", command=self.open_dir)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Remove Entry", command=self.remove_entry)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # Details
        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)
        ttk.Label(detail_frame, text="Details & Dependencies", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5,2))
        
        self.detail_text = tk.Text(detail_frame, wrap="word", height=10, font=("Consolas", 9), relief=tk.FLAT, borderwidth=1)
        dsb = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=dsb.set)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _apply_theme(self):
        theme = self.parent.current_theme
        colors = THEME_COLORS.get(theme, THEME_COLORS["light"])
        self.configure(bg=colors["bg"])
        self.detail_text.configure(bg=colors["text_bg"], fg=colors["text_fg"])

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _refresh_list(self):
        self._init_data()
        self.tree.delete(*self.tree.get_children())
        for idx, item in enumerate(self.projects_data):
            total_deps = sum(len(g.get("packages", [])) for g in item.get("dependencies", []))
            venv_cfg = item.get("venv_config", {})
            env_str = f"🧪 Venv ({venv_cfg.get('dir_name', '.venv')})" if venv_cfg.get("enabled") else "🌐 Global"
            
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", tk.END, iid=str(idx), tags=(tag,), values=(
                item.get("name", "Unknown"), env_str, item.get("path", ""), total_deps
            ))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        item = self.projects_data[idx]
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, f"PROJECT: {item.get('name')}\n")
        self.detail_text.insert(tk.END, f"PATH: {item.get('path')}\n")
        self.detail_text.insert(tk.END, "-" * 50 + "\n")
        for group in item.get("dependencies", []):
            self.detail_text.insert(tk.END, f"{group.get('type', 'UNKNOWN').upper()} ({len(group.get('packages', []))}): \n")
            for p in group.get("packages", []):
                self.detail_text.insert(tk.END, f"  • {p}\n")

    def run_app(self):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        item = self.projects_data[idx]
        cmd = item.get("run_cmd")
        path = item.get("path")
        if not cmd: return
        
        final_cmd = list(cmd)
        venv_cfg = item.get("venv_config", {})
        if venv_cfg.get("enabled"):
            venv_python = VenvHandler.get_venv_python(path, venv_cfg.get("dir_name", ".venv"))
            if os.path.exists(venv_python) and final_cmd and final_cmd[0] in [sys.executable, "python"]:
                final_cmd[0] = venv_python
                
        try: SubprocessHandler.run_command(final_cmd, cwd=path)
        except Exception as e: messagebox.showerror("Error", str(e))

    def open_dir(self):
        sel = self.tree.selection()
        if not sel: return
        path = self.projects_data[int(sel[0])].get("path")
        if path:
            if platform.system() == "Windows": os.startfile(path)
            elif platform.system() == "Darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])

    def remove_entry(self):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        if messagebox.askyesno("Confirm", "Remove this entry?"):
            del self.projects_data[idx]
            self._save_data()
            self._refresh_list()

# ---------------------------------------------------------
# Project Setup Window (Modernized)
# ---------------------------------------------------------
class ProjectSetupWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title(SETUP_ASSISTANT_TITLE)
        self.geometry("900x850") 
        self.project_path = None
        self.analysis_result = {}
        self.is_running = False
        self.use_venv_var = tk.BooleanVar(value=False)
        self.venv_name_var = tk.StringVar(value=".venv")
        self.resolved_interpreter_var = tk.StringVar(value=sys.executable)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        # Main Layout
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Source Panel
        src_group = ttk.LabelFrame(main_frame, text="1. Project Source", padding=15)
        src_group.pack(fill=tk.X, pady=(0, 15))
        
        # URL
        url_row = ttk.Frame(src_group)
        url_row.pack(fill=tk.X, pady=5)
        ttk.Label(url_row, text="GitHub URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        ttk.Entry(url_row, textvariable=self.url_var).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        ttk.Button(url_row, text="⬇ Fetch", command=self.fetch_url).pack(side=tk.LEFT)
        
        # Local
        local_row = ttk.Frame(src_group)
        local_row.pack(fill=tk.X, pady=5)
        ttk.Button(local_row, text="📂 Load Folder", command=self.load_directory).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(local_row, text="📦 Load ZIP", command=self.load_zip).pack(side=tk.LEFT)
        self.path_label_var = tk.StringVar(value="No project loaded")
        ttk.Label(local_row, textvariable=self.path_label_var, foreground="#666").pack(side=tk.LEFT, padx=15)

        # 2. Config Panel
        cfg_group = ttk.LabelFrame(main_frame, text="2. Configuration", padding=15)
        cfg_group.pack(fill=tk.X, pady=(0, 15))

        # Venv
        venv_row = ttk.Frame(cfg_group)
        venv_row.pack(fill=tk.X, pady=5)
        ttk.Checkbutton(venv_row, text="Use Virtual Environment", variable=self.use_venv_var, command=self._update_interpreter_display).pack(side=tk.LEFT)
        ttk.Label(venv_row, text="Name:").pack(side=tk.LEFT, padx=(15, 5))
        ttk.Entry(venv_row, textvariable=self.venv_name_var, width=15).pack(side=tk.LEFT)
        ttk.Label(venv_row, textvariable=self.resolved_interpreter_var, font=("Segoe UI", 8), foreground="#007aff").pack(side=tk.LEFT, padx=15)

        # Command
        cmd_row = ttk.Frame(cfg_group)
        cmd_row.pack(fill=tk.X, pady=5)
        ttk.Label(cmd_row, text="Run Command:").pack(side=tk.LEFT)
        self.run_cmd_var = tk.StringVar()
        ttk.Entry(cmd_row, textvariable=self.run_cmd_var).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # Actions
        act_row = ttk.Frame(cfg_group)
        act_row.pack(fill=tk.X, pady=(10, 0))
        self.action_buttons = {}
        def _btn(txt, cmd):
            b = ttk.Button(act_row, text=txt, command=cmd, state="disabled")
            b.pack(side=tk.LEFT, padx=2)
            self.action_buttons[txt] = b
            return b

        _btn("🔍 Analyze", self.analyze_project)
        ttk.Separator(act_row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        _btn("⚙️ Setup", self.run_setup)
        _btn("▶ Run App", self.run_application)
        _btn("📂 Open Dir", self.open_directory)

        # 3. Output
        out_group = ttk.LabelFrame(main_frame, text="3. Output & Logs", padding=15)
        out_group.pack(fill=tk.BOTH, expand=True)
        
        paned = ttk.PanedWindow(out_group, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        self.summary_text = tk.Text(paned, width=30, font=("Consolas", 9), relief=tk.FLAT, bg="#f9f9f9")
        paned.add(self.summary_text, weight=1)
        
        self.log_text = tk.Text(paned, width=50, font=("Consolas", 9), relief=tk.FLAT)
        paned.add(self.log_text, weight=2)

    def _apply_theme(self):
        theme = self.parent.current_theme
        colors = THEME_COLORS.get(theme, THEME_COLORS["light"])
        self.configure(bg=colors["bg"])
        self.summary_text.configure(bg=colors["text_bg"], fg=colors["text_fg"])
        self.log_text.configure(bg=colors["text_bg"], fg=colors["text_fg"])

    def _safe_log(self, message):
        self.after(0, lambda: self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n") or self.log_text.see(tk.END))

    def _safe_set_summary(self, text):
        self.after(0, lambda: self.summary_text.delete("1.0", tk.END) or self.summary_text.insert(tk.END, text))

    def _get_active_interpreter(self):
        if not self.project_path: return sys.executable
        return VenvHandler.get_venv_python(self.project_path, self.venv_name_var.get()) if self.use_venv_var.get() else sys.executable

    def _update_interpreter_display(self, *args):
        path = self._get_active_interpreter()
        status = " (Ready)" if os.path.exists(path) else " (Will Create)" if self.use_venv_var.get() else ""
        self.resolved_interpreter_var.set(path + status)

    def _set_project_path(self, path):
        self.project_path = path
        self.path_label_var.set(path)
        self.action_buttons["🔍 Analyze"].configure(state="normal")
        self.action_buttons["📂 Open Dir"].configure(state="normal")
        self.analyze_project()

    def load_directory(self):
        path = filedialog.askdirectory()
        if path: self._set_project_path(path)

    def load_zip(self):
        zip_path = filedialog.askopenfilename(filetypes=[("Zip Files", "*.zip")])
        if not zip_path: return
        target = filedialog.askdirectory()
        if not target: return
        name = os.path.splitext(os.path.basename(zip_path))[0]
        out = os.path.join(target, name)
        try:
            with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(out)
            self._set_project_path(out)
        except Exception as e: messagebox.showerror("Error", str(e))

    def fetch_url(self):
        url = self.url_var.get().strip()
        if not url: return
        target = filedialog.askdirectory()
        if not target: return
        name = url.split("/")[-1].replace(".git", "")
        out = os.path.join(target, name)
        
        def _worker():
            git = SubprocessHandler.find_git()
            if not git: return self._safe_log("Git not found")
            try:
                subprocess.check_call([git, "clone", url, out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.after(0, lambda: self._set_project_path(out))
            except Exception as e: self._safe_log(f"Clone failed: {e}")
        threading.Thread(target=_worker, daemon=True).start()

    def analyze_project(self):
        if not self.project_path: return
        self._safe_log("Analyzing...")
        analysis = {"types": [], "setup_cmds": [], "run_cmd": None, "env_info": {"needs_copy": False, "src": None}, "dependencies": []}
        
        root_files = set(next(os.walk(self.project_path))[2])
        if VenvHandler.detect_venv(self.project_path):
            self.use_venv_var.set(True)
            self._update_interpreter_display()

        if "requirements.txt" in root_files:
            analysis["types"].append("Python (pip)")
            analysis["setup_cmds"].append([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            analysis["dependencies"].append({"type": "python", "packages": []}) # Simplified for brevity

        if "package.json" in root_files:
            analysis["types"].append("Node.js")
            analysis["setup_cmds"].append(["npm", "install"])
            analysis["run_cmd"] = ["npm", "start"]

        if "app.py" in root_files: analysis["run_cmd"] = [sys.executable, "app.py"]
        elif "main.py" in root_files: analysis["run_cmd"] = [sys.executable, "main.py"]

        self.analysis_result = analysis
        self._update_ui_post_analysis(analysis)

    def _update_ui_post_analysis(self, analysis):
        summary = f"Detected: {', '.join(analysis['types'])}\n\nCommands:\n"
        for cmd in analysis["setup_cmds"]: summary += f" $ {' '.join(cmd)}\n"
        self._safe_set_summary(summary)
        if analysis["run_cmd"]: self.run_cmd_var.set(' '.join(analysis["run_cmd"]))
        self.action_buttons["⚙️ Setup"].configure(state="normal")
        self.action_buttons["▶ Run App"].configure(state="normal")

    def _save_project_record(self):
        if not self.project_path: return
        # Simple persistence logic (same as original, condensed)
        record = {
            "name": os.path.basename(self.project_path),
            "path": os.path.abspath(self.project_path),
            "run_cmd": shlex.split(self.run_cmd_var.get()),
            "venv_config": {"enabled": self.use_venv_var.get(), "dir_name": self.venv_name_var.get()}
        }
        data = []
        if os.path.exists(INSTALLED_PROJECTS_FILE):
            try:
                with open(INSTALLED_PROJECTS_FILE, 'r') as f: data = json.load(f)
            except: pass
        
        # Upsert
        data = [d for d in data if d['path'] != record['path']]
        data.append(record)
        
        with open(INSTALLED_PROJECTS_FILE, 'w') as f: json.dump(data, f, indent=2)

    def run_setup(self):
        if self.is_running: return
        def _worker():
            self.is_running = True
            active_python = self._get_active_interpreter()
            
            if self.use_venv_var.get() and not VenvHandler.is_venv_valid(self.project_path, self.venv_name_var.get()):
                self._safe_log("Creating venv...")
                VenvHandler.create_venv(self.project_path, self.venv_name_var.get())
            
            for cmd in self.analysis_result.get("setup_cmds", []):
                run_cmd = list(cmd)
                if run_cmd[0] == sys.executable: run_cmd[0] = active_python
                self._safe_log(f"Run: {run_cmd}")
                try: 
                    SubprocessHandler.run_command(run_cmd, cwd=self.project_path)
                    self._safe_log("OK")
                except Exception as e: self._safe_log(f"Error: {e}")
            
            self._save_project_record()
            self.is_running = False
        threading.Thread(target=_worker, daemon=True).start()

    def run_application(self):
        self._save_project_record()
        cmd = shlex.split(self.run_cmd_var.get())
        if cmd and cmd[0] in [sys.executable, "python"]:
            cmd[0] = self._get_active_interpreter()
        try: SubprocessHandler.run_command(cmd, cwd=self.project_path)
        except Exception as e: self._safe_log(f"Error: {e}")
    
    def reinstall_deps(self): self.run_setup()
    def open_directory(self): os.startfile(self.project_path) if platform.system() == "Windows" else None


# ---------------------------------------------------------
# MAIN APP (Modernized)
# ---------------------------------------------------------
class PipManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1150x700")
        
        # State
        self.snapshot_manager = SnapshotManager()
        self.command_queue = queue.Queue()
        self.all_packages = {}
        self.outdated_names = set()
        self.current_theme = "light"
        self.create_snapshot_var = tk.BooleanVar(value=False)
        self.offline_mode_var = tk.BooleanVar(value=True)
        self.project_audit_path = tk.StringVar(value=os.getcwd())
        self.embedded_project_path = tk.StringVar(value="")
        self.embedded_project_name = tk.StringVar(value="new-python-project")
        self.embedded_project_parent = tk.StringVar(value=os.getcwd())
        self.embedded_project_template = tk.StringVar(value="Desktop")
        self.embedded_use_venv_var = tk.BooleanVar(value=True)
        self.embedded_venv_name_var = tk.StringVar(value=".venv")
        self.embedded_run_cmd_var = tk.StringVar(value="")
        self.embedded_project_score_var = tk.StringVar(value="Not analyzed")
        self.app_search_var = tk.StringVar(value="")
        self.app_category_var = tk.StringVar(value="All")
        self.app_view_var = tk.StringVar(value="List")
        self.installed_app_records = []
        self.app_favorites = set()
        self.app_usage_stats = {}
        self.app_custom_tags = {}
        self._load_app_center_state()
        self.security_findings = []
        self.license_findings = []
        self.requirement_files = []
        self.requirement_findings = []
        self.policy_results = []
        self.graph_edges = []
        self.comparison_results = []
        
        # Managers
        self.audit_logger = AuditLogger()
        self.cache_manager = OfflineCacheManager()
        self.security_scanner = SecurityScanner(self.cache_manager)
        self.license_scanner = LicenseScanner()
        self.requirements_auditor = RequirementsAuditor()
        self.policy_engine = PolicyEngine()
        self.environment_comparator = EnvironmentComparator()
        self.graph_builder = SupplyChainGraphBuilder()
        self.dashboard_controller = DashboardController()
        self.plugin_manager = PluginManager(self)

        # Style & UI
        self.style = ttk.Style(self)
        self._configure_styles()
        self._build_menus()
        self._build_ui()
        self._apply_theme()
        
        self.plugin_manager.load_enabled_plugins()
        
        # Startup
        self._start_background_load()
        self.after(100, self._process_queue)
        self.refresh_snapshots_tab()
        
        # Bindings
        self.bind("<F5>", lambda e: self._start_background_load())
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind("<Delete>", lambda e: self.uninstall_selected())

    def _configure_styles(self):
        """Deep customization of ttk styles for a modern look"""
        colors = THEME_COLORS[self.current_theme]
        
        self.style.theme_use("clam")
        
        # General
        self.configure(bg=colors["bg"])
        self.style.configure(".", background=colors["bg"], foreground=colors["fg"], font=("Segoe UI", 9))
        self.style.configure("TFrame", background=colors["bg"])
        self.style.configure("Card.TFrame", background=colors["surface"], relief="solid", borderwidth=1)
        self.style.configure("TLabelframe", background=colors["bg"], bordercolor=colors["border"])
        self.style.configure("TLabelframe.Label", background=colors["bg"], foreground=colors["fg"], font=("Segoe UI", 9, "bold"))

        # Buttons
        self.style.configure("TButton", background=colors["btn_bg"], foreground=colors["fg"], borderwidth=1, focusthickness=0, padding=4)
        self.style.map("TButton", background=[("active", colors["select_bg"])], foreground=[("active", colors["select_fg"])])

        # Treeview
        self.style.configure("Treeview", 
            background=colors["tree_bg"], 
            foreground=colors["tree_fg"], 
            fieldbackground=colors["tree_bg"], 
            borderwidth=0, 
            rowheight=28,
            font=("Segoe UI", 9)
        )
        self.style.configure("Treeview.Heading", 
            background=colors["tree_hdr_bg"], 
            foreground=colors["tree_hdr_fg"], 
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=5
        )
        self.style.map("Treeview", 
            background=[("selected", colors["select_bg"])], 
            foreground=[("selected", colors["select_fg"])]
        )

        # Tabs
        self.style.configure("TNotebook", background=colors["bg"], borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=[12, 4], font=("Segoe UI", 9))

    def _apply_theme(self):
        # Update non-ttk widgets
        colors = THEME_COLORS[self.current_theme]
        for w in [self.meta_text, self.dep_text, self.snap_detail_text]:
            w.configure(bg=colors["text_bg"], fg=colors["text_fg"], insertbackground=colors["fg"])
        self._configure_styles()
        self.refresh_tree() # Re-apply tags

    def _build_menus(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Refresh Packages", accelerator="F5", command=self._start_background_load)
        file_menu.add_separator()
        file_menu.add_command(label="Export to CSV...", command=lambda: self.export_packages("csv"))
        file_menu.add_command(label="Export to JSON...", command=lambda: self.export_packages("json"))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)

        # Tools
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Project Assistant...", command=self.show_embedded_project_wizard)
        tools_menu.add_command(label="Installed Apps...", command=self.show_embedded_app_manager)
        
        # Plugins
        self.plugin_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Plugins", menu=self.plugin_menu)
        self.plugin_menu.add_command(label="Manage Plugins...", command=self.open_plugin_manager)
        self.plugin_menu.add_separator()
        
        # View (Theme)
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        self.theme_var = tk.StringVar(value="light")
        view_menu.add_radiobutton(label="Light Mode", variable=self.theme_var, value="light", command=lambda: self._set_theme("light"))
        view_menu.add_radiobutton(label="Dark Mode", variable=self.theme_var, value="dark", command=lambda: self._set_theme("dark"))

    def _build_ui(self):
        # 1. Top Bar (Grouped)
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Search Group
        search_grp = ttk.Frame(top_frame)
        search_grp.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        ttk.Label(search_grp, text="🔍").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_tree())
        self.search_entry = ttk.Entry(search_grp, textvariable=self.search_var, width=35)
        self.search_entry.pack(side=tk.LEFT)
        
        # Filter Group
        filter_grp = ttk.Frame(top_frame)
        filter_grp.pack(side=tk.LEFT, fill=tk.Y)
        self.show_outdated_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_grp, text="Show Outdated Only", variable=self.show_outdated_only, command=self.refresh_tree).pack(side=tk.LEFT)

        # 2. Main Content
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # LEFT: Package List
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)
        
        cols = ("name", "version", "health", "size", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        
        # Modern headers
        self.tree.heading("name", text="Package Name", command=lambda: self.sort_by("name", False))
        self.tree.column("name", width=250)
        self.tree.heading("version", text="Version")
        self.tree.column("version", width=100)
        self.tree.heading("health", text="Health")
        self.tree.column("health", width=120)
        self.tree.heading("size", text="Size")
        self.tree.column("size", width=80, anchor="e")
        self.tree.heading("status", text="Status")
        self.tree.column("status", width=100)

        sb_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb_y.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        # Context Menu
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="Upgrade Selected", command=self.upgrade_selected)
        self.tree_menu.add_command(label="Uninstall Selected", command=self.uninstall_selected)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Copy Name", command=self._copy_pkg_name)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # RIGHT: Details & Tools
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)
        
        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Metadata Tab
        meta_frame = ttk.Frame(self.notebook)
        self.notebook.add(meta_frame, text="📦 Metadata")
        self.meta_text = tk.Text(meta_frame, wrap="word", height=10, relief="flat", padx=10, pady=10)
        self.meta_text.pack(fill=tk.BOTH, expand=True)
        
        # Deps Tab
        dep_frame = ttk.Frame(self.notebook)
        self.notebook.add(dep_frame, text="🔗 Dependencies")
        self.dep_text = tk.Text(dep_frame, wrap="word", height=10, relief="flat", padx=10, pady=10)
        self.dep_text.pack(fill=tk.BOTH, expand=True)
        
        # Snapshots Tab
        self._build_snapshots_tab()

        # 3. Bottom Bar
        btm_frame = ttk.Frame(self, padding=10)
        btm_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Install Input
        install_grp = ttk.LabelFrame(btm_frame, text="Quick Install", padding=5)
        install_grp.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        self.install_var = tk.StringVar()
        ttk.Entry(install_grp, textvariable=self.install_var, width=25).pack(side=tk.LEFT, padx=5)
        ttk.Button(install_grp, text="Install", command=self.install_package).pack(side=tk.LEFT)

        # Actions Group
        action_grp = ttk.LabelFrame(btm_frame, text="Actions", padding=5)
        action_grp.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Button(action_grp, text="⬆ Upgrade", command=self.upgrade_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_grp, text="🗑 Uninstall", command=self.uninstall_selected).pack(side=tk.LEFT, padx=2)
        
        # Bulk Group
        bulk_grp = ttk.LabelFrame(btm_frame, text="Bulk", padding=5)
        bulk_grp.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(bulk_grp, text="Upgrade All Outdated", command=self.upgrade_all_outdated).pack(side=tk.LEFT)
        
        # Options
        opt_frame = ttk.Frame(btm_frame)
        opt_frame.pack(side=tk.RIGHT)
        ttk.Checkbutton(opt_frame, text="📸 Snapshot before changes", variable=self.create_snapshot_var).pack()

        # 4. Status Bar
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, font=("Segoe UI", 9))
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_snapshots_tab(self):
        snap_frame = ttk.Frame(self.notebook)
        self.notebook.add(snap_frame, text="⏪ Rollback")
        
        cols = ("id", "created", "count", "note")
        self.snap_tree = ttk.Treeview(snap_frame, columns=cols, show="headings", height=6)
        self.snap_tree.heading("id", text="ID"); self.snap_tree.column("id", width=0, stretch=False)
        self.snap_tree.heading("created", text="Timestamp"); self.snap_tree.column("created", width=140)
        self.snap_tree.heading("count", text="Pkgs"); self.snap_tree.column("count", width=50, anchor="center")
        self.snap_tree.heading("note", text="Note")
        
        self.snap_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.snap_tree.bind("<<TreeviewSelect>>", self._on_snapshot_select)
        
        self.snap_detail_text = tk.Text(snap_frame, height=6, relief="flat", bg="#f9f9f9", font=("Consolas", 8))
        self.snap_detail_text.pack(fill=tk.X, padx=5)
        
        btn_box = ttk.Frame(snap_frame, padding=5)
        btn_box.pack(fill=tk.X)
        ttk.Button(btn_box, text="📸 Create Now", command=self.manual_snapshot).pack(side=tk.LEFT)
        ttk.Button(btn_box, text="⏪ Restore", command=self.restore_selected_snapshot).pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="❌ Delete", command=self.delete_selected_snapshot).pack(side=tk.RIGHT, padx=5)

    def _build_ui(self):
        self.nav_buttons = {}
        self.pages = {}

        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(root, width=210, bd=0, highlightthickness=0)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="Python Governance", font=("Segoe UI", 14, "bold"), anchor="w").pack(fill=tk.X, padx=16, pady=(18, 4))
        tk.Label(self.sidebar, text="Environment Control", font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, padx=16, pady=(0, 16))

        sections = ["Dashboard", "Packages", "Dependencies", "Security", "Compliance", "Policies", "Snapshots / Rollback", "Projects", "Plugins", "Audit Logs", "Settings"]
        for section in sections:
            btn = tk.Button(self.sidebar, text=section, anchor="w", relief="flat", bd=0, padx=16, pady=9,
                            font=("Segoe UI", 10), command=lambda s=section: self._show_section(s))
            btn.pack(fill=tk.X, padx=8, pady=1)
            self.nav_buttons[section] = btn

        main = ttk.Frame(root)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.header_frame = ttk.Frame(main, padding=(18, 14, 18, 8))
        self.header_frame.pack(fill=tk.X)
        self.section_title_var = tk.StringVar(value="Dashboard")
        ttk.Label(self.header_frame, textvariable=self.section_title_var, font=("Segoe UI", 18, "bold")).pack(side=tk.LEFT)
        ttk.Button(self.header_frame, text="Run Governance Scan", command=self.run_governance_scan).pack(side=tk.RIGHT)
        ttk.Checkbutton(self.header_frame, text="Offline enforcement", variable=self.offline_mode_var).pack(side=tk.RIGHT, padx=12)

        self.content = ttk.Frame(main, padding=(18, 8, 18, 8))
        self.content.pack(fill=tk.BOTH, expand=True)
        for section in sections:
            page = ttk.Frame(self.content)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[section] = page
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_dashboard_page(self.pages["Dashboard"])
        self._build_packages_page(self.pages["Packages"])
        self._build_dependencies_page(self.pages["Dependencies"])
        self._build_security_page(self.pages["Security"])
        self._build_compliance_page(self.pages["Compliance"])
        self._build_policies_page(self.pages["Policies"])
        self._build_snapshots_page(self.pages["Snapshots / Rollback"])
        self._build_projects_page(self.pages["Projects"])
        self._build_plugins_page(self.pages["Plugins"])
        self._build_audit_page(self.pages["Audit Logs"])
        self._build_settings_page(self.pages["Settings"])

        status_frame = ttk.Frame(self, padding=(8, 4))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=140)
        self.progress.pack(side=tk.RIGHT, padx=8)
        self.status_bar = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W, font=("Segoe UI", 9))
        self.status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._show_section("Dashboard")

    def _build_dashboard_page(self, parent):
        self.kpi_frame = ttk.Frame(parent)
        self.kpi_frame.pack(fill=tk.X)
        self.kpi_vars = {}
        labels = ["Total packages", "Outdated packages", "High-risk packages", "Vulnerable packages", "License issues", "Policy violations", "Last scan time"]
        for idx, name in enumerate(labels):
            card = ttk.Frame(self.kpi_frame, padding=12, style="Card.TFrame")
            card.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=6, pady=6)
            self.kpi_frame.grid_columnconfigure(idx % 4, weight=1)
            ttk.Label(card, text=name, font=("Segoe UI", 9)).pack(anchor=tk.W)
            var = tk.StringVar(value="0" if name != "Last scan time" else "Not scanned")
            ttk.Label(card, textvariable=var, font=("Segoe UI", 18, "bold")).pack(anchor=tk.W, pady=(4, 0))
            self.kpi_vars[name] = var
        lower = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        lower.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        summary_frame = ttk.LabelFrame(lower, text="Environment Health", padding=10)
        self.dashboard_text = tk.Text(summary_frame, wrap="word", height=12, relief="flat")
        self.dashboard_text.pack(fill=tk.BOTH, expand=True)
        lower.add(summary_frame, weight=1)
        action_frame = ttk.LabelFrame(lower, text="Recommended Actions", padding=10)
        self.recommendation_text = tk.Text(action_frame, wrap="word", height=12, relief="flat")
        self.recommendation_text.pack(fill=tk.BOTH, expand=True)
        lower.add(action_frame, weight=1)

    def _build_packages_page(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(toolbar, text="Search").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_tree())
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=34)
        self.search_entry.pack(side=tk.LEFT, padx=8)
        self.show_outdated_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Outdated only", variable=self.show_outdated_only, command=self.refresh_tree).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh", command=self._start_background_load).pack(side=tk.RIGHT)
        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)
        cols = ("name", "version", "health", "size", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        for col, label, width in [("name", "Package", 260), ("version", "Version", 110), ("health", "Risk", 140), ("size", "Size", 90), ("status", "Status", 150)]:
            self.tree.heading(col, text=label, command=lambda c=col: self.sort_by(c, False))
            self.tree.column(col, width=width, anchor=tk.E if col == "size" else tk.W)
        sb_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb_y.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="Upgrade Selected", command=self.upgrade_selected)
        self.tree_menu.add_command(label="Uninstall Selected", command=self.uninstall_selected)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Copy Name", command=self._copy_pkg_name)
        self.tree.bind("<Button-3>", self._show_context_menu)
        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)
        self.detail_notebook = ttk.Notebook(detail_frame)
        self.detail_notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook = self.detail_notebook
        meta_frame = ttk.Frame(self.detail_notebook)
        self.detail_notebook.add(meta_frame, text="Metadata")
        self.meta_text = tk.Text(meta_frame, wrap="word", height=10, relief="flat", padx=10, pady=10)
        self.meta_text.pack(fill=tk.BOTH, expand=True)
        dep_frame = ttk.Frame(self.detail_notebook)
        self.detail_notebook.add(dep_frame, text="Dependencies")
        self.dep_text = tk.Text(dep_frame, wrap="word", height=10, relief="flat", padx=10, pady=10)
        self.dep_text.pack(fill=tk.BOTH, expand=True)
        bottom = ttk.Frame(parent, padding=(0, 8, 0, 0))
        bottom.pack(fill=tk.X)
        self.install_var = tk.StringVar()
        ttk.Label(bottom, text="Install").pack(side=tk.LEFT)
        ttk.Entry(bottom, textvariable=self.install_var, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Install", command=self.install_package).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Upgrade", command=self.upgrade_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Uninstall", command=self.uninstall_selected).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Upgrade all outdated", command=self.upgrade_all_outdated).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(bottom, text="Snapshot before changes", variable=self.create_snapshot_var).pack(side=tk.RIGHT)

    def _build_dependencies_page(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(top, text="Build Dependency Graph", command=self.refresh_dependency_graph).pack(side=tk.LEFT)
        ttk.Button(top, text="Audit Project Requirements", command=self.run_requirements_audit).pack(side=tk.LEFT, padx=6)
        ttk.Entry(top, textvariable=self.project_audit_path, width=70).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Browse", command=self.choose_project_audit_path).pack(side=tk.LEFT)
        self.dependency_text = tk.Text(parent, wrap="none", relief="flat", font=("Consolas", 9))
        self.dependency_text.pack(fill=tk.BOTH, expand=True)

    def _build_security_page(self, parent):
        ttk.Button(parent, text="Scan Cached Vulnerability Database", command=self.run_security_scan).pack(anchor=tk.W, pady=(0, 8))
        self.security_tree = self._make_tree(parent, ("package", "version", "id", "severity", "summary", "recommendation"), ("Package", "Version", "Vulnerability", "Severity", "Summary", "Recommendation"))

    def _build_compliance_page(self, parent):
        ttk.Button(parent, text="Scan Licenses", command=self.run_license_scan).pack(anchor=tk.W, pady=(0, 8))
        self.license_tree = self._make_tree(parent, ("package", "version", "license", "status"), ("Package", "Version", "License", "Status"))

    def _build_policies_page(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(top, text="Evaluate Policies", command=self.run_policy_check).pack(side=tk.LEFT)
        ttk.Button(top, text="Open Policy JSON", command=self.open_policy_file).pack(side=tk.LEFT, padx=6)
        self.policy_tree = self._make_tree(parent, ("policy", "status", "details"), ("Policy", "Status", "Details"))

    def _build_snapshots_page(self, parent):
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._build_snapshots_tab()

    def _build_projects_page(self, parent):
        self.projects_notebook = ttk.Notebook(parent)
        self.projects_notebook.pack(fill=tk.BOTH, expand=True)

        wizard = ttk.Frame(self.projects_notebook, padding=10)
        apps = ttk.Frame(self.projects_notebook, padding=10)
        recent = ttk.Frame(self.projects_notebook, padding=10)
        self.projects_notebook.add(wizard, text="Project Creation Wizard")
        self.projects_notebook.add(apps, text="Application Management Center")
        self.projects_notebook.add(recent, text="Recent Projects")

        self._build_embedded_project_wizard(wizard)
        self._build_embedded_app_manager(apps)
        self._build_embedded_recent_projects(recent)

    def _build_plugins_page(self, parent):
        ttk.Button(parent, text="Open Plugin Manager", command=self.open_plugin_manager).pack(anchor=tk.W, pady=(0, 8))
        self.plugin_tree = self._make_tree(parent, ("name", "version", "category", "status", "health"), ("Name", "Version", "Category", "Status", "Health"))

    def _build_embedded_project_wizard(self, parent):
        left = ttk.Frame(parent)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        right = ttk.Frame(parent)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        stats = ttk.Frame(left)
        stats.pack(fill=tk.X, pady=(0, 10))
        for label, attr in [("Score", "embedded_project_score_var"), ("Template", "embedded_project_template"), ("Path", "embedded_project_path")]:
            card = ttk.Frame(stats, padding=10, style="Card.TFrame")
            card.pack(fill=tk.X, pady=4)
            ttk.Label(card, text=label, font=("Segoe UI", 9)).pack(anchor=tk.W)
            ttk.Label(card, textvariable=getattr(self, attr), font=("Segoe UI", 11, "bold"), wraplength=260).pack(anchor=tk.W)

        cfg = ttk.LabelFrame(left, text="Project Setup", padding=10)
        cfg.pack(fill=tk.X)
        ttk.Label(cfg, text="Template").pack(anchor=tk.W)
        self.project_template_combo = ttk.Combobox(cfg, textvariable=self.embedded_project_template, state="readonly",
                                                   values=list(self._project_templates().keys()), width=28)
        self.project_template_combo.pack(fill=tk.X, pady=(2, 8))
        self.project_template_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_project_template_recommendations())
        ttk.Label(cfg, text="Project name").pack(anchor=tk.W)
        ttk.Entry(cfg, textvariable=self.embedded_project_name).pack(fill=tk.X, pady=(2, 8))
        ttk.Label(cfg, text="Parent folder").pack(anchor=tk.W)
        ttk.Entry(cfg, textvariable=self.embedded_project_parent).pack(fill=tk.X, pady=(2, 4))
        ttk.Button(cfg, text="Browse", command=self.choose_embedded_project_parent).pack(anchor=tk.W, pady=(0, 8))
        ttk.Checkbutton(cfg, text="Create virtual environment", variable=self.embedded_use_venv_var).pack(anchor=tk.W)
        ttk.Entry(cfg, textvariable=self.embedded_venv_name_var, width=16).pack(anchor=tk.W, pady=(2, 8))
        ttk.Button(cfg, text="Initialize Project", command=self.initialize_embedded_project).pack(fill=tk.X, pady=(8, 2))
        ttk.Button(cfg, text="Load Existing Project", command=self.load_embedded_project).pack(fill=tk.X, pady=2)
        ttk.Button(cfg, text="Analyze Project", command=self.analyze_embedded_project).pack(fill=tk.X, pady=2)
        ttk.Button(cfg, text="Run Project", command=self.run_embedded_project).pack(fill=tk.X, pady=2)
        ttk.Button(cfg, text="Open Folder", command=self.open_embedded_project_folder).pack(fill=tk.X, pady=2)

        self.project_wizard_notebook = ttk.Notebook(right)
        self.project_wizard_notebook.pack(fill=tk.BOTH, expand=True)
        overview = ttk.Frame(self.project_wizard_notebook)
        checks = ttk.Frame(self.project_wizard_notebook)
        starter = ttk.Frame(self.project_wizard_notebook)
        self.project_wizard_notebook.add(overview, text="Overview")
        self.project_wizard_notebook.add(checks, text="Health & Validation")
        self.project_wizard_notebook.add(starter, text="Starter Code")

        self.project_recommendation_text = tk.Text(overview, wrap="word", relief="flat", height=12)
        self.project_recommendation_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.project_health_text = tk.Text(checks, wrap="word", relief="flat", height=12)
        self.project_health_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.project_starter_text = tk.Text(starter, wrap="word", relief="flat", height=12, font=("Consolas", 9))
        self.project_starter_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.refresh_project_template_recommendations()

    def _build_embedded_app_manager(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(toolbar, text="Search").pack(side=tk.LEFT)
        self.app_search_var.trace_add("write", lambda *args: self.refresh_embedded_apps())
        ttk.Entry(toolbar, textvariable=self.app_search_var, width=30).pack(side=tk.LEFT, padx=6)
        ttk.Label(toolbar, text="Category").pack(side=tk.LEFT, padx=(12, 2))
        self.app_category_combo = ttk.Combobox(toolbar, textvariable=self.app_category_var, state="readonly", values=["All"], width=18)
        self.app_category_combo.pack(side=tk.LEFT)
        self.app_category_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_embedded_apps())
        ttk.Button(toolbar, text="Discover", command=self.discover_installed_applications).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Export", command=self.export_installed_applications).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="Repair", command=self.repair_selected_apps).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Uninstall", command=self.uninstall_selected_apps).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="Open Folder", command=self.open_selected_app_folder).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Launch", command=self.launch_selected_app).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="Favorite", command=self.toggle_selected_app_favorite).pack(side=tk.RIGHT)
        ttk.Combobox(toolbar, textvariable=self.app_view_var, state="readonly", values=["List", "Grid", "Cards"], width=8).pack(side=tk.RIGHT, padx=6)

        paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.apps_tree = self._make_tree(paned, ("favorite", "name", "category", "version", "publisher", "status", "health", "path"),
                                         ("Fav", "Application", "Category", "Version", "Publisher", "Status", "Health", "Path"))
        paned.add(self.apps_tree.master, weight=3)
        detail = ttk.Frame(paned)
        paned.add(detail, weight=2)
        self.app_detail_text = tk.Text(detail, wrap="word", relief="flat")
        self.app_detail_text.pack(fill=tk.BOTH, expand=True)
        self.apps_tree.bind("<<TreeviewSelect>>", self.on_embedded_app_select)
        self.apps_tree.bind("<Double-1>", lambda e: self.launch_selected_app())
        self.discover_installed_applications(background=True)

    def _build_embedded_recent_projects(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_recent_projects).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Open Selected", command=self.open_recent_project).pack(side=tk.LEFT, padx=6)
        ttk.Button(toolbar, text="Run Selected", command=self.run_recent_project).pack(side=tk.LEFT)
        self.recent_projects_tree = self._make_tree(parent, ("name", "template", "score", "path", "updated"),
                                                    ("Name", "Template", "Score", "Path", "Updated"))
        self.refresh_recent_projects()

    def _project_templates(self):
        return {
            "Desktop": {"deps": ["tkinter (stdlib)", "pillow"], "run": "python main.py", "files": {"main.py": "import tkinter as tk\n\nroot = tk.Tk()\nroot.title('Desktop App')\ntk.Label(root, text='Hello from Tkinter').pack(padx=24, pady=24)\nroot.mainloop()\n"}},
            "CLI": {"deps": ["click", "rich"], "run": "python main.py", "files": {"main.py": "import argparse\n\nparser = argparse.ArgumentParser()\nparser.add_argument('--name', default='World')\nargs = parser.parse_args()\nprint(f'Hello, {args.name}!')\n"}},
            "Web": {"deps": ["flask", "python-dotenv"], "run": "python app.py", "files": {"app.py": "from flask import Flask\n\napp = Flask(__name__)\n\n@app.get('/')\ndef index():\n    return {'status': 'ok'}\n\nif __name__ == '__main__':\n    app.run(debug=True)\n"}},
            "API": {"deps": ["fastapi", "uvicorn"], "run": "python -m uvicorn app:app --reload", "files": {"app.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n"}},
            "Library": {"deps": ["pytest", "build"], "run": "python -m pytest", "files": {"src/__init__.py": "__version__ = '0.1.0'\n", "tests/test_basic.py": "def test_basic():\n    assert True\n"}},
            "Plugin": {"deps": [], "run": "python -m py_compile plugin.py", "files": {"manifest.json": "{\n  \"id\": \"custom.plugin\",\n  \"name\": \"Custom Plugin\",\n  \"version\": \"0.1.0\",\n  \"author\": \"Local\",\n  \"description\": \"Starter plugin\",\n  \"category\": \"Governance\",\n  \"permissions\": [\"packages:read\"],\n  \"api_version\": \"1.0\",\n  \"entry\": \"plugin.py\",\n  \"enabled\": false\n}\n", "plugin.py": "class Plugin:\n    def on_load(self, context):\n        context.log('Custom plugin loaded')\n"}}
        }

    def refresh_project_template_recommendations(self):
        template = self._project_templates().get(self.embedded_project_template.get(), {})
        deps = template.get("deps", [])
        files = template.get("files", {})
        self.embedded_run_cmd_var.set(template.get("run", "python main.py"))
        text = [
            f"Template: {self.embedded_project_template.get()}",
            f"Recommended run command: {self.embedded_run_cmd_var.get()}",
            "",
            "Recommended dependencies:",
            *[f" - {dep}" for dep in deps],
            "",
            "Generated structure:",
            *[f" - {path}" for path in files],
            "",
            "Best practices:",
            " - Use a virtual environment per project.",
            " - Pin runtime dependencies before release.",
            " - Keep tests, README, and configuration files in source control.",
            " - Run governance scans before installing or upgrading dependencies."
        ]
        if hasattr(self, "project_recommendation_text"):
            self.project_recommendation_text.delete("1.0", tk.END)
            self.project_recommendation_text.insert(tk.END, "\n".join(text))
        if hasattr(self, "project_starter_text"):
            self.project_starter_text.delete("1.0", tk.END)
            for path, content in files.items():
                self.project_starter_text.insert(tk.END, f"# {path}\n{content}\n\n")

    def choose_embedded_project_parent(self):
        path = filedialog.askdirectory(initialdir=self.embedded_project_parent.get() or os.getcwd())
        if path:
            self.embedded_project_parent.set(path)

    def load_embedded_project(self):
        path = filedialog.askdirectory(initialdir=self.embedded_project_parent.get() or os.getcwd())
        if path:
            self.embedded_project_path.set(path)
            self.project_audit_path.set(path)
            self.analyze_embedded_project()

    def initialize_embedded_project(self):
        template = self._project_templates().get(self.embedded_project_template.get(), {})
        parent = self.embedded_project_parent.get() or os.getcwd()
        name = re.sub(r"[^A-Za-z0-9_.-]+", "-", self.embedded_project_name.get().strip() or "new-python-project")
        path = os.path.abspath(os.path.join(parent, name))
        try:
            os.makedirs(path, exist_ok=True)
            for rel_path, content in template.get("files", {}).items():
                full = os.path.join(path, rel_path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if not os.path.exists(full):
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(content)
            reqs = [d for d in template.get("deps", []) if "(stdlib)" not in d]
            if reqs:
                with open(os.path.join(path, "requirements.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(reqs) + "\n")
            readme = os.path.join(path, "README.md")
            if not os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as f:
                    f.write(f"# {name}\n\nGenerated by Python Environment Governance Platform.\n")
            if self.embedded_use_venv_var.get() and not VenvHandler.is_venv_valid(path, self.embedded_venv_name_var.get()):
                VenvHandler.create_venv(path, self.embedded_venv_name_var.get())
            self.embedded_project_path.set(path)
            self.project_audit_path.set(path)
            self.audit_logger.log("project_initialized", {"path": path, "template": self.embedded_project_template.get()})
            self._save_embedded_project_record(path)
            self.analyze_embedded_project()
            messagebox.showinfo("Project Initialized", f"Project created at:\n{path}")
        except Exception as e:
            messagebox.showerror("Project Initialization Failed", str(e))

    def _save_embedded_project_record(self, path):
        record = {
            "name": os.path.basename(path),
            "path": os.path.abspath(path),
            "template": self.embedded_project_template.get(),
            "score": self.embedded_project_score_var.get(),
            "run_cmd": shlex.split(self.embedded_run_cmd_var.get()),
            "venv_config": {"enabled": self.embedded_use_venv_var.get(), "dir_name": self.embedded_venv_name_var.get()},
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data = []
        if os.path.exists(INSTALLED_PROJECTS_FILE):
            try:
                with open(INSTALLED_PROJECTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []
        data = [item for item in data if item.get("path") != record["path"]]
        data.insert(0, record)
        with open(INSTALLED_PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if hasattr(self, "recent_projects_tree"):
            self.refresh_recent_projects()

    def analyze_embedded_project(self):
        path = self.embedded_project_path.get()
        if not path or not os.path.isdir(path):
            messagebox.showwarning("Project", "Load or initialize a project first.")
            return
        files = set(next(os.walk(path))[2])
        folders = set(next(os.walk(path))[1])
        score = 100
        findings = []
        checks = []
        py_version = sys.version.split()[0]
        git = SubprocessHandler.find_git()
        pip_rc, pip_out, _ = SubprocessHandler.run_command([sys.executable, "-m", "pip", "--version"], capture_output=True)
        compiler = shutil.which("cl") or shutil.which("gcc") or shutil.which("clang")
        venv_name = VenvHandler.detect_venv(path)
        if not venv_name:
            score -= 15
            findings.append("No virtual environment detected.")
        if "requirements.txt" not in files and "pyproject.toml" not in files:
            score -= 15
            findings.append("No requirements.txt or pyproject.toml found.")
        if "README.md" not in files:
            score -= 10
            findings.append("README.md is missing.")
        if "tests" not in folders:
            score -= 10
            findings.append("Tests folder is missing.")
        if not git:
            score -= 5
            findings.append("Git executable was not detected.")
        req_files, req_findings = self.requirements_auditor.audit(path, self.all_packages)
        unpinned = [r for r in req_findings if r.get("issue") == "Unpinned"]
        if unpinned:
            score -= min(20, len(unpinned) * 2)
        score = max(0, score)
        self.embedded_project_score_var.set(f"{score}/100")
        checks.extend([
            f"Project: {path}",
            f"Python version: {py_version}",
            f"pip: {(pip_out or 'Unavailable').strip() if pip_rc == 0 else 'Unavailable'}",
            f"Virtual environment: {venv_name or 'Not detected'}",
            f"Git: {git or 'Not detected'}",
            f"Compiler/toolchain: {compiler or 'Not detected'}",
            f"Requirement files: {len(req_files)}",
            f"Requirement findings: {len(req_findings)}",
            "",
            "Optimization suggestions:"
        ])
        checks.extend([f" - {item}" for item in findings] or [" - Project follows the local best-practice checks."])
        if unpinned:
            checks.append(f" - Pin {len(unpinned)} unpinned dependency entries.")
        self.project_health_text.delete("1.0", tk.END)
        self.project_health_text.insert(tk.END, "\n".join(checks))
        self._save_embedded_project_record(path)
        self.audit_logger.log("project_analyzed", {"path": path, "score": score})

    def run_embedded_project(self):
        path = self.embedded_project_path.get()
        if not path or not os.path.isdir(path):
            return
        cmd = shlex.split(self.embedded_run_cmd_var.get())
        if cmd and cmd[0] in [sys.executable, "python"]:
            venv_python = VenvHandler.get_venv_python(path, self.embedded_venv_name_var.get())
            if self.embedded_use_venv_var.get() and os.path.exists(venv_python):
                cmd[0] = venv_python
        if cmd:
            SubprocessHandler.run_command(cmd, cwd=path)
            self.audit_logger.log("project_run", {"path": path, "cmd": cmd})

    def open_embedded_project_folder(self):
        path = self.embedded_project_path.get()
        if path and os.path.isdir(path):
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])

    def refresh_recent_projects(self):
        data = []
        if os.path.exists(INSTALLED_PROJECTS_FILE):
            try:
                with open(INSTALLED_PROJECTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []
        rows = []
        for item in data:
            rows.append({
                "name": item.get("name", os.path.basename(item.get("path", ""))),
                "template": item.get("template", item.get("env_type", "Detected")),
                "score": item.get("score", ""),
                "path": item.get("path", ""),
                "updated": item.get("updated", "")
            })
        if hasattr(self, "recent_projects_tree"):
            self._populate_tree(self.recent_projects_tree, rows, ("name", "template", "score", "path", "updated"))

    def _selected_recent_project(self):
        sel = self.recent_projects_tree.selection()
        if not sel:
            return None
        return self.recent_projects_tree.set(sel[0], "path")

    def open_recent_project(self):
        path = self._selected_recent_project()
        if path:
            self.embedded_project_path.set(path)
            self.project_audit_path.set(path)
            self.projects_notebook.select(0)
            self.analyze_embedded_project()

    def run_recent_project(self):
        self.open_recent_project()
        self.run_embedded_project()

    def discover_installed_applications(self, background=False):
        def worker():
            records = self._discover_windows_applications() if platform.system() == "Windows" else self._discover_local_project_apps()
            self.installed_app_records = records
            self.after(0, self.refresh_embedded_apps)
        if background:
            threading.Thread(target=worker, daemon=True).start()
        else:
            worker()

    def _discover_windows_applications(self):
        records = []
        try:
            import winreg
            roots = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
            ]
            for root, key_path in roots:
                try:
                    key = winreg.OpenKey(root, key_path)
                except OSError:
                    continue
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                        item = {}
                        for field in ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation", "InstallDate", "UninstallString", "EstimatedSize"):
                            try:
                                item[field] = winreg.QueryValueEx(sub, field)[0]
                            except OSError:
                                item[field] = ""
                        if not item.get("DisplayName"):
                            continue
                        records.append(self._normalize_app_record(item))
                    except OSError:
                        continue
        except Exception:
            records = self._discover_local_project_apps()
        return sorted(records, key=lambda x: x["name"].lower())

    def _discover_local_project_apps(self):
        data = []
        if os.path.exists(INSTALLED_PROJECTS_FILE):
            try:
                with open(INSTALLED_PROJECTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []
        return [{
            "name": item.get("name", "Project"),
            "version": "",
            "publisher": "Local Project",
            "path": item.get("path", ""),
            "install_date": item.get("updated", ""),
            "size": "",
            "startup": "Manual",
            "running": "Unknown",
            "update": "Local",
            "category": "Development",
            "health": "Managed",
            "security": "Local project",
            "uninstall": "",
            "tags": ""
        } for item in data]

    def _normalize_app_record(self, item):
        path = str(item.get("InstallLocation") or "")
        size_kb = item.get("EstimatedSize") or 0
        try:
            size = f"{int(size_kb) / 1024:,.1f} MB" if size_kb else ""
        except Exception:
            size = ""
        name = str(item.get("DisplayName", ""))
        category = self._categorize_app(name, item.get("Publisher", ""), path)
        running = self._is_app_running(name)
        health = "Review" if not path else "Healthy"
        security = "Unknown signature"
        return {
            "name": name,
            "version": item.get("DisplayVersion", ""),
            "publisher": item.get("Publisher", ""),
            "path": path,
            "install_date": item.get("InstallDate", ""),
            "size": size,
            "startup": "Manual",
            "running": "Running" if running else "Stopped",
            "update": "Unknown",
            "category": category,
            "health": health,
            "security": security,
            "uninstall": item.get("UninstallString", ""),
            "tags": self.app_custom_tags.get(name, "")
        }

    def _categorize_app(self, name, publisher, path):
        text = f"{name} {publisher} {path}".lower()
        rules = [
            ("Development", ("python", "git", "visual studio", "node", "docker", "code", "java", "sdk")),
            ("Security", ("security", "defender", "vpn", "antivirus", "firewall")),
            ("Productivity", ("office", "word", "excel", "notepad", "pdf", "adobe")),
            ("Browser", ("chrome", "edge", "firefox", "browser")),
            ("Database", ("sql", "postgres", "mysql", "mongodb", "redis")),
            ("Runtime", ("runtime", "redistributable", ".net", "java")),
        ]
        for category, needles in rules:
            if any(n in text for n in needles):
                return category
        return "General"

    def _is_app_running(self, name):
        try:
            rc, out, _ = SubprocessHandler.run_command(["tasklist"], capture_output=True)
            return rc == 0 and name.split()[0].lower() in out.lower()
        except Exception:
            return False

    def refresh_embedded_apps(self):
        categories = ["All"] + sorted({app.get("category", "General") for app in self.installed_app_records})
        if hasattr(self, "app_category_combo"):
            self.app_category_combo.configure(values=categories)
        search = self.app_search_var.get().lower()
        category = self.app_category_var.get()
        rows = []
        for app in self.installed_app_records:
            if category and category != "All" and app.get("category") != category:
                continue
            haystack = " ".join(str(app.get(k, "")) for k in ("name", "publisher", "path", "category", "tags")).lower()
            if search and search not in haystack:
                continue
            status = f"{app.get('running', 'Unknown')} / {app.get('startup', 'Manual')}"
            rows.append({
                "favorite": "*" if app.get("name") in self.app_favorites else "",
                "name": app.get("name", ""),
                "category": app.get("category", ""),
                "version": app.get("version", ""),
                "publisher": app.get("publisher", ""),
                "status": status,
                "health": app.get("health", ""),
                "path": app.get("path", "")
            })
        if hasattr(self, "apps_tree"):
            self._populate_tree(self.apps_tree, rows, ("favorite", "name", "category", "version", "publisher", "status", "health", "path"))

    def _selected_app_record(self):
        sel = self.apps_tree.selection()
        if not sel:
            return None
        name = self.apps_tree.set(sel[0], "name")
        return next((app for app in self.installed_app_records if app.get("name") == name), None)

    def on_embedded_app_select(self, event=None):
        app = self._selected_app_record()
        if not app:
            return
        self.app_detail_text.delete("1.0", tk.END)
        details = [
            f"Application: {app.get('name')}",
            f"Version: {app.get('version') or 'Unknown'}",
            f"Publisher: {app.get('publisher') or 'Unknown'}",
            f"Category: {app.get('category')}",
            f"Install path: {app.get('path') or 'Unknown'}",
            f"Install date: {app.get('install_date') or 'Unknown'}",
            f"Size: {app.get('size') or 'Unknown'}",
            f"Startup status: {app.get('startup')}",
            f"Running status: {app.get('running')}",
            f"Update availability: {app.get('update')}",
            f"Health: {app.get('health')}",
            f"Digital signature: {app.get('security')}",
            f"Tags: {app.get('tags') or 'None'}",
            f"Launch count: {self.app_usage_stats.get(app.get('name'), 0)}",
            "",
            "Contextual actions: launch, favorite, open installation folder, export inventory."
        ]
        self.app_detail_text.insert(tk.END, "\n".join(details))

    def launch_selected_app(self):
        app = self._selected_app_record()
        if not app:
            return
        path = app.get("path", "")
        try:
            if path and os.path.isdir(path):
                candidates = [p for p in os.listdir(path) if p.lower().endswith(".exe")]
                if candidates and platform.system() == "Windows":
                    os.startfile(os.path.join(path, candidates[0]))
            self.app_usage_stats[app["name"]] = self.app_usage_stats.get(app["name"], 0) + 1
            self._save_app_center_state()
            self.audit_logger.log("application_launch", {"name": app["name"]})
            self.on_embedded_app_select()
        except Exception as e:
            messagebox.showerror("Launch Failed", str(e))

    def open_selected_app_folder(self):
        app = self._selected_app_record()
        path = app.get("path") if app else None
        if path and os.path.isdir(path):
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])

    def toggle_selected_app_favorite(self):
        app = self._selected_app_record()
        if not app:
            return
        name = app.get("name")
        if name in self.app_favorites:
            self.app_favorites.remove(name)
        else:
            self.app_favorites.add(name)
        self._save_app_center_state()
        self.refresh_embedded_apps()
        self.audit_logger.log("application_favorite_toggle", {"name": name})

    def export_installed_applications(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("All Files", "*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.installed_app_records, f, indent=2)
            else:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["name", "version", "publisher", "category", "path", "install_date", "size", "running", "health", "security"])
                    writer.writeheader()
                    for row in self.installed_app_records:
                        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
            self.audit_logger.log("application_inventory_export", {"path": path, "count": len(self.installed_app_records)})
            messagebox.showinfo("Export", "Application inventory exported.")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def show_embedded_project_wizard(self):
        self._show_section("Projects")
        if hasattr(self, "projects_notebook"):
            self.projects_notebook.select(0)

    def show_embedded_app_manager(self):
        self._show_section("Projects")
        if hasattr(self, "projects_notebook"):
            self.projects_notebook.select(1)
        self.refresh_embedded_apps()

    def _load_app_center_state(self):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        if not os.path.exists(APP_CENTER_STATE_FILE):
            return
        try:
            with open(APP_CENTER_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.app_favorites = set(data.get("favorites", []))
            self.app_usage_stats = data.get("usage_stats", {})
            self.app_custom_tags = data.get("custom_tags", {})
        except Exception:
            self.app_favorites = set()
            self.app_usage_stats = {}
            self.app_custom_tags = {}

    def _save_app_center_state(self):
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        data = {
            "favorites": sorted(self.app_favorites),
            "usage_stats": self.app_usage_stats,
            "custom_tags": self.app_custom_tags
        }
        try:
            with open(APP_CENTER_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _selected_app_records(self):
        rows = []
        for iid in self.apps_tree.selection():
            name = self.apps_tree.set(iid, "name")
            app = next((item for item in self.installed_app_records if item.get("name") == name), None)
            if app:
                rows.append(app)
        return rows

    def uninstall_selected_apps(self):
        apps = self._selected_app_records()
        if not apps:
            return
        runnable = [app for app in apps if app.get("uninstall")]
        if not runnable:
            messagebox.showinfo("Uninstall", "No uninstall command is available for the selected application.")
            return
        names = ", ".join(app["name"] for app in runnable[:5])
        if len(runnable) > 5:
            names += f" and {len(runnable) - 5} more"
        if not messagebox.askyesno("Confirm Uninstall", f"Run uninstall command for {names}?"):
            return
        for app in runnable:
            try:
                SubprocessHandler.run_command(shlex.split(app["uninstall"]))
                self.audit_logger.log("application_uninstall_requested", {"name": app["name"]})
            except Exception as e:
                self.audit_logger.log("application_uninstall_failed", {"name": app["name"], "error": str(e)}, "error")

    def repair_selected_apps(self):
        apps = self._selected_app_records()
        if not apps:
            return
        repaired = 0
        for app in apps:
            uninstall = app.get("uninstall", "")
            match = re.search(r"\{[A-Fa-f0-9-]{36}\}", uninstall)
            if "msiexec" in uninstall.lower() and match:
                try:
                    SubprocessHandler.run_command(["msiexec.exe", "/fa", match.group(0), "/qn"])
                    self.audit_logger.log("application_repair_requested", {"name": app["name"]})
                    repaired += 1
                except Exception as e:
                    self.audit_logger.log("application_repair_failed", {"name": app["name"], "error": str(e)}, "error")
        if not repaired:
            messagebox.showinfo("Repair", "No MSI repair command could be inferred for the selected applications.")

    def _build_audit_page(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, pady=(0, 8))
        self.audit_filter_var = tk.StringVar()
        ttk.Label(top, text="Filter").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.audit_filter_var, width=30).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh_audit_logs).pack(side=tk.LEFT)
        ttk.Button(top, text="Export JSONL", command=self.export_audit_logs).pack(side=tk.LEFT, padx=6)
        self.audit_tree = self._make_tree(parent, ("timestamp", "action", "status", "details"), ("Timestamp", "Action", "Status", "Details"))

    def _build_settings_page(self, parent):
        ttk.Label(parent, text="Theme", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))
        ttk.Radiobutton(parent, text="Light mode", variable=self.theme_var, value="light", command=lambda: self._set_theme("light")).pack(anchor=tk.W)
        ttk.Radiobutton(parent, text="Dark mode", variable=self.theme_var, value="dark", command=lambda: self._set_theme("dark")).pack(anchor=tk.W)
        ttk.Checkbutton(parent, text="Offline enforcement mode", variable=self.offline_mode_var).pack(anchor=tk.W, pady=(12, 0))
        ttk.Label(parent, text=f"Governance data directory: {os.path.abspath(APP_DATA_DIR)}").pack(anchor=tk.W, pady=(16, 0))

    def _make_tree(self, parent, cols, labels):
        frame = ttk.Frame(parent)
        if not isinstance(parent, ttk.PanedWindow):
            frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col, label in zip(cols, labels):
            tree.heading(col, text=label)
            tree.column(col, width=160, anchor=tk.W)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        return tree

    def _apply_theme(self):
        colors = THEME_COLORS[self.current_theme]
        self._configure_styles()
        self.configure(bg=colors["bg"])
        if hasattr(self, "sidebar"):
            self.sidebar.configure(bg=colors["sidebar_bg"])
            for child in self.sidebar.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=colors["sidebar_bg"], fg=colors["sidebar_fg"])
        for name, btn in getattr(self, "nav_buttons", {}).items():
            active = getattr(self, "active_section", "Dashboard") == name
            btn.configure(
                bg=colors["sidebar_active"] if active else colors["sidebar_bg"],
                fg="#ffffff" if active else colors["sidebar_fg"],
                activebackground=colors["sidebar_active"],
                activeforeground="#ffffff"
            )
        for attr in ("meta_text", "dep_text", "snap_detail_text", "dashboard_text", "recommendation_text", "dependency_text", "project_recommendation_text", "project_health_text", "project_starter_text", "app_detail_text"):
            widget = getattr(self, attr, None)
            if widget:
                widget.configure(bg=colors["text_bg"], fg=colors["text_fg"], insertbackground=colors["fg"])
        self.refresh_tree()

    def _show_section(self, section):
        self.active_section = section
        self.section_title_var.set(section)
        self.pages[section].tkraise()
        self._apply_theme()
        if section == "Plugins":
            self.refresh_plugins_page()
        elif section == "Audit Logs":
            self.refresh_audit_logs()

    def _populate_tree(self, tree, rows, cols):
        tree.delete(*tree.get_children())
        for idx, row in enumerate(rows):
            values = [row.get(col, "") for col in cols]
            tree.insert("", tk.END, iid=str(idx), values=values)

    def run_governance_scan(self):
        self.plugin_manager.notify_scan_requested()
        self.run_security_scan()
        self.run_license_scan()
        self.run_requirements_audit()
        self.run_policy_check()
        self.refresh_dependency_graph()
        self.dashboard_controller.last_scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audit_logger.log("scan_execution", {"offline": self.offline_mode_var.get(), "packages": len(self.all_packages)})
        self.refresh_dashboard()
        self._set_status("Governance scan complete.", "ready")

    def refresh_dashboard(self):
        kpis = self.dashboard_controller.kpis(self.all_packages, self.security_findings, self.license_findings, self.policy_results)
        for name, value in kpis.items():
            if name in self.kpi_vars:
                self.kpi_vars[name].set(str(value))
        high_risk = [p for p in self.all_packages.values() if p.health_status == "High Risk"]
        self.dashboard_text.delete("1.0", tk.END)
        self.dashboard_text.insert(tk.END, f"Python: {sys.version.split()[0]}\n")
        self.dashboard_text.insert(tk.END, f"Interpreter: {sys.executable}\n")
        self.dashboard_text.insert(tk.END, f"Virtual environment: {'Yes' if sys.prefix != getattr(sys, 'base_prefix', sys.prefix) else 'No'}\n")
        self.dashboard_text.insert(tk.END, f"Offline enforcement: {'Enabled' if self.offline_mode_var.get() else 'Disabled'}\n")
        self.dashboard_text.insert(tk.END, f"High-risk packages: {len(high_risk)}\n")
        self.dashboard_text.insert(tk.END, f"Cached vulnerability DB: {self.security_scanner.cache_updated_at or 'No timestamp'}\n")
        self.recommendation_text.delete("1.0", tk.END)
        if self.outdated_names:
            self.recommendation_text.insert(tk.END, f"Create a rollback snapshot before upgrading {len(self.outdated_names)} outdated packages.\n")
        if self.security_findings:
            self.recommendation_text.insert(tk.END, "Review vulnerable packages and prefer patch/minor updates first.\n")
        if any(r.get("status") == "Fail" for r in self.policy_results):
            self.recommendation_text.insert(tk.END, "Resolve failed policy checks before approving environment changes.\n")
        if not self.recommendation_text.get("1.0", tk.END).strip():
            self.recommendation_text.insert(tk.END, "No urgent recommendations from local governance checks.")

    def run_security_scan(self):
        self.security_findings = self.security_scanner.scan({k.lower(): v for k, v in self.all_packages.items()})
        self._populate_tree(self.security_tree, self.security_findings, ("package", "version", "id", "severity", "summary", "recommendation"))
        self.audit_logger.log("security_scan", {"findings": len(self.security_findings), "offline_cache": True})
        self.refresh_dashboard()

    def run_license_scan(self):
        blocked = []
        for policy in self.policy_engine.load():
            if policy.get("type") == "blocked_license" and policy.get("enabled", True):
                blocked.extend(policy.get("licenses", []))
        self.license_findings = self.license_scanner.scan(self.all_packages, blocked)
        self._populate_tree(self.license_tree, self.license_findings, ("package", "version", "license", "status"))
        self.audit_logger.log("license_scan", {"findings": len(self.license_findings)})
        self.refresh_dashboard()

    def run_requirements_audit(self):
        root = self.project_audit_path.get() or os.getcwd()
        self.requirement_files, self.requirement_findings = self.requirements_auditor.audit(root, self.all_packages)
        self.dependency_text.delete("1.0", tk.END)
        self.dependency_text.insert(tk.END, "Requirement files:\n")
        for path in self.requirement_files:
            self.dependency_text.insert(tk.END, f"  {path}\n")
        self.dependency_text.insert(tk.END, "\nFindings:\n")
        for row in self.requirement_findings[:500]:
            self.dependency_text.insert(tk.END, f"  {row['issue']}: {row['package']} declared={row['declared']} installed={row['installed']}\n")
        self.audit_logger.log("requirements_audit", {"root": root, "findings": len(self.requirement_findings)})

    def run_policy_check(self):
        self.policy_results = self.policy_engine.evaluate(self.all_packages, self.security_findings, self.license_findings, self.requirement_findings)
        self._populate_tree(self.policy_tree, self.policy_results, ("policy", "status", "details"))
        self.plugin_manager.notify_policy_check(self.policy_results)
        self.audit_logger.log("policy_check", {"failures": len([p for p in self.policy_results if p.get("status") == "Fail"])})
        self.refresh_dashboard()

    def refresh_dependency_graph(self):
        self.graph_edges = self.graph_builder.build_edges(self.all_packages)
        self.dependency_text.delete("1.0", tk.END)
        self.dependency_text.insert(tk.END, "Supply chain dependency edges (direct and transitive roots shown by package metadata):\n\n")
        for edge in self.graph_edges[:1000]:
            marker = "!" if edge["risk"] == "High Risk" or not edge["installed"] else "-"
            self.dependency_text.insert(tk.END, f"{marker} {edge['source']} -> {edge['target']} [{edge['risk']}]\n")
        if len(self.graph_edges) > 1000:
            self.dependency_text.insert(tk.END, f"\n... {len(self.graph_edges) - 1000} additional edges omitted from view.\n")

    def choose_project_audit_path(self):
        path = filedialog.askdirectory(initialdir=self.project_audit_path.get() or os.getcwd())
        if path:
            self.project_audit_path.set(path)

    def open_policy_file(self):
        if platform.system() == "Windows":
            os.startfile(os.path.abspath(POLICY_FILE))
        else:
            messagebox.showinfo("Policy File", os.path.abspath(POLICY_FILE))

    def refresh_plugins_page(self):
        rows = self.plugin_manager.discover_plugins()
        self._populate_tree(self.plugin_tree, rows, ("name", "version", "category", "status", "health"))

    def refresh_audit_logs(self):
        rows = self.audit_logger.read(action_filter=self.audit_filter_var.get() if hasattr(self, "audit_filter_var") else None)
        for row in rows:
            row["details"] = json.dumps(row.get("details", {}), ensure_ascii=True)
        self._populate_tree(self.audit_tree, rows, ("timestamp", "action", "status", "details"))

    def export_audit_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".jsonl", filetypes=[("JSONL", "*.jsonl"), ("All Files", "*.*")])
        if path:
            shutil.copyfile(AUDIT_LOG_FILE, path)
            self.audit_logger.log("audit_export", {"path": path})
            messagebox.showinfo("Export", "Audit log exported.")

    def _set_theme(self, theme):
        self.current_theme = theme
        self.theme_var.set(theme)
        self._apply_theme()

    def _copy_pkg_name(self):
        sel = self.tree.selection()
        if sel:
            self.clipboard_clear()
            self.clipboard_append(sel[0])

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def sort_by(self, col, descending):
        data = []
        for iid in self.tree.get_children(""):
            val = self.tree.set(iid, col)
            data.append((val, iid))
        data.sort(reverse=descending)
        for idx, (_, iid) in enumerate(data): self.tree.move(iid, "", idx)
        self.tree.heading(col, command=lambda: self.sort_by(col, not descending))

    # --- Core Logic Integration ---

    def _process_queue(self):
        try:
            while True:
                cmd, payload = self.command_queue.get_nowait()
                if cmd == "packages_loaded":
                    self.all_packages = {p.name: p for p in payload}
                    self.cache_manager.save_package_metadata(payload)
                    self._set_status(f"Loaded {len(self.all_packages)} packages.", "ready")
                    self.refresh_tree()
                    self.plugin_manager.notify_packages_loaded()
                    self.refresh_plugins_page()
                    self.refresh_dashboard()
                elif cmd == "outdated_loaded":
                    self.outdated_names = payload or set()
                    for name in self.outdated_names:
                        if name in self.all_packages: self.all_packages[name].outdated = True
                    self.refresh_tree()
                    self.refresh_dashboard()
                elif cmd == "status": self._set_status(payload, "busy")
                elif cmd == "plugin_log":
                    self.plugin_manager.log_plugin(payload.get("plugin_id", "unknown"), payload.get("message", ""))
                    self._set_status(f"Plugin {payload.get('plugin_id', '')}: {payload.get('message', '')}", "ready")
                elif cmd == "error": 
                    self._set_status("Error encountered", "error")
                    messagebox.showerror("Error", str(payload))
                elif cmd == "operation_done":
                    self._set_status(payload, "ready")
                    self._start_background_load()
                elif cmd == "refresh_snapshots": self.refresh_snapshots_tab()
        except queue.Empty: pass
        self.after(100, self._process_queue)

    def _set_status(self, text, state="ready"):
        label = "BUSY" if state == "busy" else "OK" if state == "ready" else "WARN"
        self.status_var.set(f" {label}  {text}")
        if state == "busy":
            self.config(cursor="watch")
            if hasattr(self, "progress"): self.progress.start(10)
        else:
            self.config(cursor="")
            if hasattr(self, "progress"): self.progress.stop()
        return
        icon = "⏳" if state == "busy" else "✅" if state == "ready" else "⚠️"
        self.status_var.set(f" {icon} {text}")
        if state == "busy":
            self.config(cursor="watch")
            if hasattr(self, "progress"): self.progress.start(10)
        else:
            self.config(cursor="")
            if hasattr(self, "progress"): self.progress.stop()

    def _start_background_load(self):
        self._set_status("Loading package list...", "busy")
        threading.Thread(target=self._load_packages_thread, daemon=True).start()
        threading.Thread(target=self._load_outdated_thread, daemon=True).start()

    def _load_packages_thread(self):
        try:
            pkgs = self._gather_package_info()
            pkg_map = {p.name: p for p in pkgs}
            HealthEngine.analyze_all(pkg_map)
            self.command_queue.put(("packages_loaded", pkgs))
        except Exception as e:
            self.command_queue.put(("error", f"Error: {e}"))

    def _load_outdated_thread(self):
        try:
            cmd = [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"]
            rc, out, _ = SubprocessHandler.run_command(cmd, capture_output=True)
            if rc == 0:
                data = json.loads(out or "[]")
                names = {item.get("name") for item in data}
                self.command_queue.put(("outdated_loaded", names))
        except: pass

    def _gather_package_info(self):
        pkgs = []
        for dist in metadata.distributions():
            try:
                meta = dist.metadata
                name = meta.get("Name", meta.get("Summary", ""))
                if not name: continue
                version = dist.version
                summary = meta.get("Summary", "")
                try: location = str(dist.locate_file(""))
                except: location = ""
                size_bytes, latest_mtime = 0, None
                try:
                    files = list(dist.files) or []
                    for f in files:
                        p = dist.locate_file(f)
                        if p.is_file():
                            st = p.stat()
                            size_bytes += st.st_size
                            mt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                            if latest_mtime is None or mt > latest_mtime: latest_mtime = mt
                except: pass
                has_entry_points = False
                try: 
                    if dist.entry_points: has_entry_points = True
                except: pass
                requires = dist.requires or []
                metadata_text = "\n".join([f"{k}: {meta[k]}" for k in meta])
                pkgs.append(PackageInfo(name, version, summary, location, size_bytes, latest_mtime, requires, metadata_text, has_entry_points))
            except: continue
        return pkgs

    def refresh_tree(self):
        search = (self.search_var.get() or "").strip().lower()
        show_outdated = self.show_outdated_only.get()
        self.tree.delete(*self.tree.get_children())
        
        # Configure Zebra Striping tags with theme colors
        colors = THEME_COLORS[self.current_theme]
        self.tree.tag_configure("even", background=colors["row_even"])
        self.tree.tag_configure("odd", background=colors["row_odd"])

        for idx, pkg in enumerate(self.all_packages.values()):
            if search and search not in pkg.name.lower(): continue
            if show_outdated and not pkg.outdated: continue
            
            # Badges
            health_badge = pkg.health_status
            
            status_badges = []
            if pkg.outdated: status_badges.append("🟡 Outdated")
            if pkg.is_recent: status_badges.append("✨ New")
            status_str = " ".join(status_badges)
            status_labels = []
            if pkg.outdated: status_labels.append("Outdated")
            if pkg.is_recent: status_labels.append("New")
            status_str = ", ".join(status_labels)

            tag = "even" if idx % 2 == 0 else "odd"
            
            self.tree.insert("", tk.END, iid=pkg.name, tags=(tag,), values=(
                pkg.name, pkg.version, health_badge, f"{pkg.size_mb:,.1f} MB", status_str
            ))

    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        pkg = self.all_packages.get(sel[0])
        if not pkg: return
        self.meta_text.delete("1.0", tk.END)
        self.meta_text.insert(tk.END, f"{pkg.name} {pkg.version}\n")
        self.meta_text.insert(tk.END, "=" * 48 + "\n")
        self.meta_text.insert(tk.END, f"Summary: {pkg.summary}\n")
        self.meta_text.insert(tk.END, f"Location: {pkg.location}\n")
        self.meta_text.insert(tk.END, f"Size: {pkg.size_mb:,.1f} MB\n")
        self.meta_text.insert(tk.END, f"Health: {pkg.health_status}\n")
        self.meta_text.insert(tk.END, f"Outdated: {'Yes' if pkg.outdated else 'No'}\n\n")
        if pkg.health_reasons:
            self.meta_text.insert(tk.END, "Risk factors:\n")
            for r in pkg.health_reasons:
                self.meta_text.insert(tk.END, f" - {r}\n")
        else:
            self.meta_text.insert(tk.END, "Risk factors: none detected by local checks.\n")
        self.meta_text.insert(tk.END, "\nRaw metadata:\n" + pkg.metadata_text)
        self.dep_text.delete("1.0", tk.END)
        self.dep_text.insert(tk.END, "Direct dependencies:\n")
        if pkg.requires_simple:
            for r in pkg.requires_simple:
                self.dep_text.insert(tk.END, f" - {r}\n")
        else:
            self.dep_text.insert(tk.END, " None")
        return

        self.meta_text.delete("1.0", tk.END)
        self.meta_text.insert(tk.END, f"📦 {pkg.name} v{pkg.version}\n")
        self.meta_text.insert(tk.END, f"📄 {pkg.summary}\n")
        self.meta_text.insert(tk.END, f"📍 {pkg.location}\n")
        self.meta_text.insert(tk.END, "-"*40 + "\n")
        
        if pkg.health_reasons:
            self.meta_text.insert(tk.END, "⚠️ Risk Factors:\n")
            for r in pkg.health_reasons: self.meta_text.insert(tk.END, f" • {r}\n")
        else:
            self.meta_text.insert(tk.END, "✅ No significant risks detected.\n")
            
        self.meta_text.insert(tk.END, "\nRaw Metadata:\n" + pkg.metadata_text)
        
        self.dep_text.delete("1.0", tk.END)
        self.dep_text.insert(tk.END, "Direct Dependencies:\n")
        if pkg.requires_simple:
            for r in pkg.requires_simple: self.dep_text.insert(tk.END, f" • {r}\n")
        else:
            self.dep_text.insert(tk.END, " (None)")

    # --- Snapshots, Pip Ops (Preserved) ---
    def refresh_snapshots_tab(self):
        self.snap_tree.delete(*self.snap_tree.get_children())
        snapshots = self.snapshot_manager.get_snapshots()
        for s in snapshots:
            self.snap_tree.insert("", tk.END, iid=s["id"], values=(s["id"], s["created_at"], len(s["packages"]), s.get("note", "")))
    
    def _on_snapshot_select(self, event):
        sel = self.snap_tree.selection()
        if not sel: return
        s = next((x for x in self.snapshot_manager.get_snapshots() if x["id"] == sel[0]), None)
        self.snap_detail_text.delete("1.0", tk.END)
        if s: self.snap_detail_text.insert(tk.END, "\n".join(s["packages"]))

    def manual_snapshot(self):
        note = simpledialog.askstring("Snapshot", "Note:")
        if note is not None:
            threading.Thread(target=self._create_snapshot_thread, args=(sys.executable, note), daemon=True).start()

    def _create_snapshot_thread(self, interp, note):
        success, res = self.snapshot_manager.create_snapshot(interp, note)
        self.audit_logger.log("snapshot_creation", {"note": note, "interpreter": interp}, "ok" if success else "error")
        self.command_queue.put(("refresh_snapshots", None))
        self.command_queue.put(("status", "Snapshot created" if success else f"Error: {res}"))

    def delete_selected_snapshot(self):
        sel = self.snap_tree.selection()
        if sel and messagebox.askyesno("Confirm", "Delete snapshot?"):
            self.snapshot_manager.delete_snapshot(sel[0])
            self.audit_logger.log("snapshot_delete", {"snapshot_id": sel[0]})
            self.refresh_snapshots_tab()

    def restore_selected_snapshot(self):
        sel = self.snap_tree.selection()
        if not sel: return
        s = next((x for x in self.snapshot_manager.get_snapshots() if x["id"] == sel[0]), None)
        if s and messagebox.askyesno("Restore", "Rollback packages?"):
            threading.Thread(target=self._rollback_thread, args=(s,), daemon=True).start()

    def _rollback_thread(self, s):
        self.audit_logger.log("rollback_started", {"snapshot_id": s.get("id")})
        RollbackEngine.restore_snapshot(s, lambda m: self.command_queue.put(("status", m)))
        self.audit_logger.log("rollback_finished", {"snapshot_id": s.get("id")})
        self.command_queue.put(("operation_done", "Rollback finished"))

    def _run_pip_thread(self, args, msg, snap_note=None):
        if snap_note: self.snapshot_manager.create_snapshot(sys.executable, snap_note)
        self.command_queue.put(("status", msg))
        SubprocessHandler.run_command([sys.executable, "-m", "pip"] + args)
        self.command_queue.put(("operation_done", "Done"))

    def _confirm_snapshot_for_change(self, action):
        if self.create_snapshot_var.get():
            return f"Pre-{action}"
        choice = messagebox.askyesnocancel("Rollback Protection", f"Create a rollback snapshot before {action}?")
        if choice is None:
            return None
        return f"Pre-{action}" if choice else ""

    def install_package(self):
        pkg = self.install_var.get()
        if pkg:
            note = self._confirm_snapshot_for_change("install")
            if note is None: return
            self.audit_logger.log("package_install", {"package": pkg})
            threading.Thread(target=self._run_pip_thread, args=(["install", pkg], "Installing...", note or None), daemon=True).start()

    def uninstall_selected(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Confirm", "Uninstall?"):
            note = self._confirm_snapshot_for_change("uninstall")
            if note is None: return
            self.audit_logger.log("package_uninstall", {"packages": list(sel)})
            threading.Thread(target=self._run_pip_thread, args=(["uninstall", "-y"] + list(sel), "Uninstalling...", note or None), daemon=True).start()

    def upgrade_selected(self):
        sel = self.tree.selection()
        if not sel: return
        note = self._confirm_snapshot_for_change("upgrade")
        if note is None: return
        self.audit_logger.log("package_upgrade", {"packages": list(sel)})
        threading.Thread(target=self._run_pip_thread, args=(["install", "--upgrade"] + list(sel), "Upgrading...", note or None), daemon=True).start()

    def upgrade_all_outdated(self):
        if self.outdated_names:
            note = self._confirm_snapshot_for_change("bulk-upgrade")
            if note is None: return
            self.audit_logger.log("package_bulk_upgrade", {"packages": list(self.outdated_names)})
            threading.Thread(target=self._run_pip_thread, args=(["install", "--upgrade"] + list(self.outdated_names), "Upgrading all...", note or None), daemon=True).start()

    def export_packages(self, fmt):
        pkgs = list(self.all_packages.values())
        path = filedialog.asksaveasfilename(defaultextension=f".{fmt}")
        if path:
            try:
                if fmt == "csv":
                    with open(path, "w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(["name", "version", "health"])
                        for p in pkgs: w.writerow([p.name, p.version, p.health_status])
                else:
                    with open(path, "w") as f: json.dump([{"name": p.name} for p in pkgs], f)
                self.plugin_manager.notify_export(path, fmt)
                self.audit_logger.log("package_export", {"path": path, "format": fmt, "count": len(pkgs)})
                messagebox.showinfo("Success", "Exported")
            except Exception as e: messagebox.showerror("Error", str(e))

    def open_plugin_manager(self): PluginManagerWindow(self, self.plugin_manager)

if __name__ == "__main__":
    app = PipManagerApp()
    app.mainloop()
