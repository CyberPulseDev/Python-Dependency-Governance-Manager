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

# --- Theme Definitions ---
# Enhanced palette for better visual hierarchy and modern look
THEME_COLORS = {
    "light": {
        "bg": "#f5f5f7", "fg": "#1d1d1f",
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

# --- Plugin Architecture ---

class PluginContext:
    def __init__(self, app_instance):
        self._app = app_instance
    def log(self, message):
        self._app.command_queue.put(("status", f"[Plugin] {message}"))
    def add_tab(self, title, widget_factory):
        try:
            frame = ttk.Frame(self._app.notebook)
            widget = widget_factory(frame)
            widget.pack(fill=tk.BOTH, expand=True)
            self._app.notebook.add(frame, text=title)
        except Exception as e:
            print(f"Plugin failed to add tab: {e}")
    def add_menu_command(self, label, command):
        try:
            self._app.plugin_menu.add_command(label=label, command=command)
        except Exception as e:
            print(f"Plugin failed to add menu: {e}")
    def get_packages_snapshot(self):
        return [{"name": p.name, "version": p.version} for p in self._app.all_packages.values()]

class PluginBase:
    def on_load(self, context): pass
    def on_packages_loaded(self, context, packages): pass

class PluginManager:
    def __init__(self, app_instance):
        self.app = app_instance
        self.plugins = {}
        self.config = self._load_config()
        self._ensure_plugin_dir()
        self.context = PluginContext(self.app)

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
            "api_version": PLUGIN_API_VERSION, "entry": "plugin.py"
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
                with open(PLUGIN_CONFIG_FILE, "r") as f: return json.load(f)
            except: pass
        return {"enabled": []}

    def save_config(self):
        with open(PLUGIN_CONFIG_FILE, "w") as f: json.dump(self.config, f, indent=2)

    def discover_plugins(self):
        discovered = []
        if not os.path.exists(PLUGIN_DIR): return []
        for d in os.listdir(PLUGIN_DIR):
            path = os.path.join(PLUGIN_DIR, d)
            man_path = os.path.join(path, "manifest.json")
            if os.path.isdir(path) and os.path.exists(man_path):
                try:
                    with open(man_path, "r") as f: meta = json.load(f)
                    if meta.get("api_version") != PLUGIN_API_VERSION: continue
                    meta["dir_path"] = path
                    discovered.append(meta)
                except: pass
        return discovered

    def load_enabled_plugins(self):
        plugins = self.discover_plugins()
        enabled_ids = set(self.config.get("enabled", []))
        for p_meta in plugins:
            if p_meta["id"] in enabled_ids: self.load_plugin(p_meta)

    def load_plugin(self, meta):
        try:
            entry_file = os.path.join(meta["dir_path"], meta["entry"])
            spec = importlib.util.spec_from_file_location(f"plugin_{meta['id']}", entry_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "Plugin"):
                instance = module.Plugin()
                self.plugins[meta["id"]] = instance
                if hasattr(instance, "on_load"): instance.on_load(self.context)
        except Exception as e:
            print(f"Failed to load plugin {meta['id']}: {e}")
            self.toggle_plugin(meta["id"], False)

    def toggle_plugin(self, plugin_id, enable=True):
        enabled = set(self.config.get("enabled", []))
        if enable: enabled.add(plugin_id)
        else: enabled.discard(plugin_id)
        self.config["enabled"] = list(enabled)
        self.save_config()

    def notify_packages_loaded(self):
        pkgs = self.context.get_packages_snapshot()
        for pid, instance in self.plugins.items():
            if hasattr(instance, "on_packages_loaded"):
                try: instance.on_packages_loaded(self.context, pkgs)
                except: pass

class PluginManagerWindow(tk.Toplevel):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.title(PLUGIN_MANAGER_TITLE)
        self.geometry("600x400")
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        # Header
        hdr = ttk.Frame(self, padding=15)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Manage Plugins", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        
        # List
        cols = ("name", "version", "status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("version", text="Version")
        self.tree.heading("status", text="Status")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # Footer
        btn_frame = ttk.Frame(self, padding=15)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Toggle Selected", command=self.toggle_selection).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        self.refresh()

    def _apply_theme(self):
        theme = self.master.current_theme if hasattr(self.master, 'current_theme') else "light"
        colors = THEME_COLORS.get(theme, THEME_COLORS["light"])
        self.configure(bg=colors["bg"])

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
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
        
        # Managers
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
        tools_menu.add_command(label="Project Assistant...", command=lambda: ProjectSetupWindow(self))
        tools_menu.add_command(label="Installed Apps...", command=lambda: InstalledAppsWindow(self))
        
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
                    self._set_status(f"Loaded {len(self.all_packages)} packages.", "ready")
                    self.refresh_tree()
                    self.plugin_manager.notify_packages_loaded()
                elif cmd == "outdated_loaded":
                    self.outdated_names = payload or set()
                    for name in self.outdated_names:
                        if name in self.all_packages: self.all_packages[name].outdated = True
                    self.refresh_tree()
                elif cmd == "status": self._set_status(payload, "busy")
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
        icon = "⏳" if state == "busy" else "✅" if state == "ready" else "⚠️"
        self.status_var.set(f" {icon} {text}")
        if state == "busy": self.config(cursor="watch")
        else: self.config(cursor="")

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
            health_badge = f"{pkg.health_badge} {pkg.health_status}"
            
            status_badges = []
            if pkg.outdated: status_badges.append("🟡 Outdated")
            if pkg.is_recent: status_badges.append("✨ New")
            status_str = " ".join(status_badges)

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
        self.command_queue.put(("refresh_snapshots", None))
        self.command_queue.put(("status", "Snapshot created" if success else f"Error: {res}"))

    def delete_selected_snapshot(self):
        sel = self.snap_tree.selection()
        if sel and messagebox.askyesno("Confirm", "Delete snapshot?"):
            self.snapshot_manager.delete_snapshot(sel[0])
            self.refresh_snapshots_tab()

    def restore_selected_snapshot(self):
        sel = self.snap_tree.selection()
        if not sel: return
        s = next((x for x in self.snapshot_manager.get_snapshots() if x["id"] == sel[0]), None)
        if s and messagebox.askyesno("Restore", "Rollback packages?"):
            threading.Thread(target=self._rollback_thread, args=(s,), daemon=True).start()

    def _rollback_thread(self, s):
        RollbackEngine.restore_snapshot(s, lambda m: self.command_queue.put(("status", m)))
        self.command_queue.put(("operation_done", "Rollback finished"))

    def _run_pip_thread(self, args, msg, snap_note=None):
        if snap_note: self.snapshot_manager.create_snapshot(sys.executable, snap_note)
        self.command_queue.put(("status", msg))
        SubprocessHandler.run_command([sys.executable, "-m", "pip"] + args)
        self.command_queue.put(("operation_done", "Done"))

    def install_package(self):
        pkg = self.install_var.get()
        if pkg: threading.Thread(target=self._run_pip_thread, args=(["install", pkg], "Installing..."), daemon=True).start()

    def uninstall_selected(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Confirm", "Uninstall?"):
            threading.Thread(target=self._run_pip_thread, args=(["uninstall", "-y"] + list(sel), "Uninstalling..."), daemon=True).start()

    def upgrade_selected(self):
        sel = self.tree.selection()
        if not sel: return
        note = "Pre-upgrade" if self.create_snapshot_var.get() else None
        threading.Thread(target=self._run_pip_thread, args=(["install", "--upgrade"] + list(sel), "Upgrading...", note), daemon=True).start()

    def upgrade_all_outdated(self):
        if self.outdated_names:
            note = "Pre-bulk-upgrade" if self.create_snapshot_var.get() else None
            threading.Thread(target=self._run_pip_thread, args=(["install", "--upgrade"] + list(self.outdated_names), "Upgrading all...", note), daemon=True).start()

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
                messagebox.showinfo("Success", "Exported")
            except Exception as e: messagebox.showerror("Error", str(e))

    def open_plugin_manager(self): PluginManagerWindow(self, self.plugin_manager)

if __name__ == "__main__":
    app = PipManagerApp()
    app.mainloop()