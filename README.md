# 🚀 Pip Package Manager

> **Enterprise Python Environment Governance Platform**  
> A modern desktop application for Python package management, project creation, application management, dependency governance, security review, rollback protection, and plugin-based extensibility.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-success)
![License](https://img.shields.io/badge/License-MIT-green)
![Offline](https://img.shields.io/badge/Offline-Supported-orange)
![Plugins](https://img.shields.io/badge/Plugin%20Architecture-Enabled-purple)

---

## 📌 Overview

**Pip Package Manager** started as a desktop GUI for managing Python packages and has evolved into a full **Python Environment Governance Platform**.

It combines:

- Python package management
- Dependency health analysis
- Environment snapshots and rollback
- Enterprise policy checks
- Security and license review
- Requirements auditing
- Offline governance cache support
- Supply-chain dependency insight
- Embedded project creation
- Embedded application management
- Extensible plugin architecture

The application is designed to remain **local-first**, **offline-capable**, and **safe by default**.

---

# ✨ Key Highlights

- 🏠 Professional sidebar dashboard
- 📦 Package install, upgrade, uninstall, and outdated detection
- 📊 KPI cards for package, risk, policy, license, and security visibility
- 🛡 Governance engines for audit, policy, security, license, and requirements review
- 🔄 Snapshot and rollback protection before risky package changes
- 🧩 Enterprise plugin system with permissions, lifecycle hooks, health status, logs, and reload support
- 🛠 Embedded Project Creation Wizard
- 🖥 Embedded Application Management Center
- 📂 Recent Projects workspace
- 🌐 Offline cache support for governance data
- 🎨 Light and Dark mode

---

# 🏠 Modern Workspace

The old pop-up based project tools have been replaced with a unified embedded workspace.

The **Projects** section now includes:

- **Project Creation Wizard**
- **Application Management Center**
- **Recent Projects**

The Tools menu items now route into these embedded tabs instead of launching separate windows:

- `Project Assistant...`
- `Installed Apps...`

This keeps the workflow inside one clean professional interface.

---

# 🛠 Project Creation Wizard

Create new Python projects from built-in templates.

## Included Templates

- Desktop Application
- CLI Application
- Web Application
- API Project
- Python Library
- Plugin Project

## Project Initialization Features

The wizard can generate:

- Starter source files
- `requirements.txt`
- `README.md`
- Optional virtual environment
- Initial project structure
- Toolchain checks
- Environment detection
- Health scoring
- Dependency recommendations
- Recent project persistence

This helps users create cleaner Python projects faster while following better development practices.

---

# 🖥 Application Management Center

The embedded Application Management Center replaces the old separate Installed Applications window.

## Features

- Installed application discovery
- Category detection
- Advanced search and filtering
- Launch application
- Open application folder
- Favorite applications
- Export application inventory
- Running status detection
- Health and security fields
- Usage statistics
- Repair request hooks
- Uninstall request hooks
- Persistent favorites and usage stats

Application state is stored locally in:

```text
governance_data/application_center_state.json
```

---

# 📂 Recent Projects

The Recent Projects tab provides quick access to previously created or opened projects.

It supports:

- Recent project persistence
- One-click project access
- Project metadata
- Environment overview
- Project health context

---

# 📊 Dashboard

The main dashboard provides KPI cards for:

- Total packages
- Outdated packages
- High-risk packages
- Vulnerable packages
- License issues
- Policy violations
- Last scan time

---

# 📦 Package Management

Core package operations are preserved:

- Install packages
- Upgrade selected packages
- Upgrade all outdated packages
- Uninstall packages
- Search packages
- Filter outdated packages
- View package metadata
- View direct dependencies
- Export package list to CSV or JSON

Risky actions can trigger rollback protection through snapshots.

---

# 🔄 Snapshot & Rollback

The snapshot system allows safer package changes.

## Snapshot Features

- Manual environment snapshots
- Optional pre-change snapshots
- Snapshot notes
- Snapshot deletion
- Environment restore

## Rollback Process

Snapshots are created using `pip freeze` and restored using pip-based requirements restoration.

This avoids destructive filesystem-level rollback and keeps recovery transparent.

---

# 🧠 Environment Health Engine

The health engine evaluates packages using local signals such as:

| Signal | Description |
|---|---|
| Stale package | Package has not changed for a long period |
| Large package | Package has a large local footprint |
| Deep dependency chain | Package has many dependency levels |
| Executable entry points | Package exposes command-line entry points |

Health states:

- 🟢 Healthy
- 🟡 Moderate Risk
- 🔴 High Risk

---

# 🛡 Governance Engines

The platform includes several governance engines:

## AuditLogger

Stores important application actions in local audit logs.

Examples:

- Install
- Upgrade
- Uninstall
- Rollback
- Snapshot creation
- Plugin enable/disable
- Governance scan
- Policy evaluation

## PolicyEngine

Supports local JSON-based policies such as:

- No unpinned dependencies
- Block high severity vulnerabilities
- Block selected licenses
- Require virtual environment usage

## SecurityScanner

Scans installed packages against locally cached vulnerability information.

## LicenseScanner

Extracts package license metadata and highlights risky or unknown licenses.

## RequirementsAuditor

Audits supported project dependency files:

- `requirements.txt`
- `pyproject.toml`
- `Pipfile`
- `setup.py`
- `setup.cfg`

Findings may include:

- Missing packages
- Extra packages
- Unpinned dependencies
- Outdated packages

## EnvironmentComparator

Compares snapshots or environments to show:

- Added packages
- Removed packages
- Changed versions

## OfflineCacheManager

Maintains local governance cache files for offline operation.

## SupplyChainGraphBuilder

Builds dependency relationships for supply-chain visibility.

## DashboardController

Aggregates governance and package data for dashboard KPIs.

---

# 🌐 Offline Governance Data

The application stores governance data locally in:

```text
governance_data/
├── policies.json
├── vulnerability_cache.json
├── package_metadata_cache.json
├── audit_logs.jsonl
└── application_center_state.json
```

The platform is designed to remain useful even when offline.

---

# 🔌 Enterprise Plugin System

The plugin architecture has been upgraded with:

- Plugin manifests
- Permissions
- Lifecycle hooks
- Error isolation
- Health/status tracking
- Reload support
- Plugin logs
- Rich plugin manager UI

## Plugin Structure

```text
plugins/
└── example_stats/
    ├── manifest.json
    └── plugin.py
```

## Manifest Example

```json
{
  "id": "example.plugin.stats",
  "name": "Package Statistics",
  "version": "1.0.0",
  "author": "System",
  "description": "Adds package statistics.",
  "category": "Reporting",
  "permissions": ["packages:read"],
  "api_version": "1.0",
  "entry": "plugin.py",
  "enabled": false
}
```

## Supported Plugin Hooks

- `on_load`
- `on_unload`
- `on_packages_loaded`
- `on_scan_requested`
- `on_policy_check`
- `on_export`

Plugins are isolated so a broken plugin does not crash the main application.

---

# 🏗 Technical Architecture

The following diagram illustrates the high-level architecture of the application, showing how the Enterprise Dashboard, Core Manager, Governance Engines, Project Workspace, Local Storage, and Plugin Framework interact.

> <img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/a303eb51-7072-43f0-9ada-76e0db62c4f7" />

<p align="center">
  <img src="images/architecture.png" alt="Pip Package Manager Architecture" width="100%">
</p>

The architecture follows a modular, enterprise-oriented design where the **Core Manager / Controller** orchestrates communication between the user interface, governance engines, project workspace, plugin framework, and local storage while remaining fully offline-capable.


# 🎨 User Interface

The application includes:

- Sidebar navigation
- Dashboard cards
- Professional workspace layout
- Search and filters
- Treeview status badges
- Context menus
- Progress-aware status bar
- Light mode
- Dark mode

Main sections include:

- Dashboard
- Packages
- Dependencies
- Security
- Compliance
- Policies
- Snapshots / Rollback
- Projects
- Plugins
- Audit Logs
- Settings

---

# 🗃 Runtime Data Files

| File / Folder | Purpose |
|---|---|
| `installed_projects.json` | Saved project records |
| `pip_snapshots.json` | Environment snapshots |
| `plugins/plugins.json` | Enabled plugin list |
| `plugins/*` | Plugin definitions |
| `governance_data/policies.json` | Local policy rules |
| `governance_data/vulnerability_cache.json` | Offline vulnerability cache |
| `governance_data/package_metadata_cache.json` | Offline package metadata |
| `governance_data/audit_logs.jsonl` | Local audit log |
| `governance_data/application_center_state.json` | Application Center favorites and usage state |

---

# 🖥 Requirements

- Python 3.8+
- Tkinter
- pip
- Git optional, for cloning projects
- Packaging module recommended for advanced version comparison

---

# 🚀 How to Run

```bash
python "Pip Package Manager.py"
```

or, depending on your filename:

```bash
python Pip_Package_Manager.py
```

---

# 🔒 Safety Principles

This project follows these principles:

- No telemetry
- Offline-first design
- User-confirmed risky actions
- Rollback protection
- No hidden background package modification
- Local data storage
- Plugin permission boundaries
- Backward compatibility where possible

---

# 🛣 Roadmap

There are currently **no planned roadmap items**. Development is driven by ongoing improvements, community feedback, bug fixes, and new enterprise features as they are identified.

---

# 📜 License

This project is licensed under the MIT License.

---

## 📷 Application Screenshots
<img width="1145" height="746" alt="image" src="https://github.com/user-attachments/assets/b9f1ee92-6024-4c28-b87a-d402bb5b7f51" />
<img width="1143" height="744" alt="image" src="https://github.com/user-attachments/assets/b7b33660-c59e-4bfe-bc8e-7fabe8634b05" />
<img width="1141" height="737" alt="image" src="https://github.com/user-attachments/assets/a74a64e5-23d7-4141-b703-0ad5847ffd24" />
<img width="1145" height="744" alt="image" src="https://github.com/user-attachments/assets/86ba3362-2942-4443-8b1a-48d13804ba08" />

---
# 🙌 Final Note

Pip Package Manager is no longer just a pip GUI.

It is becoming a complete **local-first Python Environment Governance Platform** for developers, power users, DevOps teams, and security-conscious environments.

If you find the project useful, please consider giving it a ⭐ on GitHub.
