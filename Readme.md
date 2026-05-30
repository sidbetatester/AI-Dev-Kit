# Project Tools Runner

**Project Tools Runner** is a versatile Tkinter-based desktop application for developers, technical writers, and project managers to streamline project management, analysis, and sharing. It offers a clean, intuitive interface to:

1. **Concatenate Project Files**: Combine all text-based files in your project into a single `.txt` file for easy sharing, backups, or AI code reviews.
2. **Visualize Project Structure**: Map your directory structure into an interactive, multi-column tree view enriched with file metadata like size, creation date, and last-modified date.
3. **Analyze Projects**: Get detailed insights with folder counts, metadata, and advanced filtering options to explore and document your project effortlessly.

This tool is perfect for organizing large codebases, generating documentation, and preparing projects for AI-assisted workflows.

It ships as **three interfaces over the same core tools**: the **desktop app** (this Tkinter UI), a **privacy-first web app** that runs entirely in your browser ([details](#web-app-browser-privacy-first)), and a local, read-only **MCP server** for AI agents ([details](#mcp-server-ai-agent-access)).

---

## Table of Contents

- [Key Features](#key-features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Guide](#usage-guide)
  - [Main Interface](#main-interface)
  - [Project Tree Views](#project-tree-views)
  - [Settings and Controls](#settings-and-controls)
  - [Output Files](#output-files)
  - [Advanced Features](#advanced-features)
- [Web App (Browser, Privacy-First)](#web-app-browser-privacy-first)
  - [How It Works](#how-it-works)
  - [Running the Web App](#running-the-web-app)
  - [Web Interface Guide](#web-interface-guide)
    - [Main Interface](#main-interface-web)
    - [Project Tree View](#project-tree-view-web)
    - [Toolbar Controls](#toolbar-controls-web)
    - [Concatenated Files and Logs](#concatenated-files-and-logs-web)
  - [Source Modes](#source-modes)
  - [Privacy Guarantees](#privacy-guarantees)
- [MCP Server (AI Agent Access)](#mcp-server-ai-agent-access)
  - [What It Is](#what-it-is)
  - [Installation](#mcp-installation)
  - [Running the Server](#running-the-server)
  - [Connecting an AI Client](#connecting-an-ai-client)
  - [Available Tools](#available-tools)
  - [Security Model](#security-model)
- [Technical Details](#technical-details)
  - [Workflow Diagrams](#workflow-diagrams)
  - [File Processing](#file-processing)
  - [Tree Visualization](#tree-visualization)
- [FAQ and Troubleshooting](#faq-and-troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Key Features

### Core Functionality
- **File Loader Tool**: Automatically combines all text-based files into a single `.txt` file while skipping binary files and excluded directories.
- **Project Structure Visualization**: Generates a detailed JSON representation of your directory and displays it in a multi-column, interactive tree view.
- **Snapshot Management**: Save and reload tree states for easy comparison and reference.

### Advanced Features
- **Interactive Controls**: Expand or collapse directories, search by name, filter by file type, and toggle metadata columns (size, created, modified).
- **Copy Tree as Text**: Export the visible tree structure (filtered view) as a clean ASCII representation for documentation or sharing.
- **Partial Collapse**: Collapse the tree to only display top-level directories while preserving current states.
- **Preserved States**: Toggle excluded directories without resetting the tree view.

### User Interface
- **Flexible Layout**: Collapsible tree and console panels, responsive design, and tooltips for intuitive navigation.
- **Console Logging**: Real-time logging for operations, errors, and file processing details.

---

## Installation

This project is managed with [Astral's `uv`](https://github.com/astral-sh/uv).
`pyproject.toml` is the single source of truth for dependencies and `uv.lock` pins
exact, reproducible versions. The recommended workflow uses `uv`; a `pip` fallback is
provided for environments where `uv` is unavailable.

### Recommended: `uv`

1. **Install uv** (once) — see the [official instructions](https://docs.astral.sh/uv/getting-started/installation/), or:
   ```bash
   pip install uv
   ```

2. **Clone the repository**:
   ```bash
   git clone https://github.com/sidbetatester/AI-Dev-Kit.git
   cd AI-Dev-Kit
   ```

3. **Sync dependencies** (creates an isolated, locked environment in `.venv`):
   ```bash
   uv sync                 # desktop + web app
   uv sync --extra mcp     # also include the MCP server (Python 3.10+)
   ```

4. **Run any interface** through uv (no need to activate the environment):
   ```bash
   uv run python tool_runner_ui.py     # desktop app (needs Tkinter + a display)
   uv run python webapp/app.py         # web app  → http://localhost:5000
   uv run python mcp_server.py --root /path/to/project   # MCP server
   ```

> Linux desktop users also need Tkinter from the system package manager:
> `sudo apt-get install python3-tk`.

### Fallback: `pip`

The `requirements*.txt` files are kept in sync with `pyproject.toml` for pip users.

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt     # desktop + web app
# optional MCP server (Python 3.10+):
pip install -r requirements.txt -r requirements-mcp.txt
python tool_runner_ui.py
```

---

## Quick Start

1. Open the application and select your **Project Root** using the "Browse..." button.
2. Choose an **Output Directory** (default is `Tools_Outputs`).
3. Select tools to run:
   - File Loader: Concatenates files into a single `.txt`.
   - Project Structure: Visualizes the folder hierarchy.
4. Click **Run Tools** to start processing.
5. Use the tree view to navigate your project or export it as ASCII text.

---

## Usage Guide

### Main Interface

![Main Interface](images/Screenshot_Project_Tools_Runner_1.png)

The main window offers:
- **Directory Selection**: Choose the project root and output directory.
- **Tool Selection**: Select File Loader, Project Structure, or both.
- **Excludes Configuration**: Toggle default excludes and edit the comma-separated list of directory names (e.g., `.git`, `venv`, `node_modules`) that are skipped during scans.
- **Output Configuration**: Set file names for concatenated output, structure JSON, and logs.
- **Run Controls**: Start, clear logs, or toggle the console/tree view.

---

### Project Tree Views

#### Full Tree with Metadata
![Full Tree with Metadata](images/Screenshot_Project_Tools_Runner_4_tree.png)

Explore your project with:
- File sizes (bytes).
- Creation and last-modified timestamps.
- Folder counts for directories.

#### Compact Tree View
![Compact Tree View](images/Screenshot_Project_Tools_Runner_3_tree.png)

Switch to a simplified view that focuses on structure alone.

---

### Settings and Controls

![Settings and Controls](images/Screenshot_Project_Tools_Runner_6_Settings&Controls.png)

Key controls include:
- **Expand All/Collapse All**: Quickly navigate the tree.
- **Search and Filter**: Find specific files or extensions in real time.
- **Snapshot Management**: Save or load the current tree view.
- **Toggle Columns**: Show or hide metadata like size, created, and modified.
- **Show Excluded Dirs**: Control whether directories in the active excludes list are shown in the tree or hidden from view.
- **Persistent Settings**: The excludes checkbox and list are saved between sessions, so your preferred skip rules are restored on restart.

---

### Output Files

1. **Concatenated Text File** (`loaded_files_output.txt`):
   - Contains all text files combined.
   - Skips binary files and excluded directories.

2. **Project Structure JSON** (`project_structure.json`):
   - Hierarchical representation of the project.
   - Includes file metadata and folder relationships.

3. **Log File** (`file_loader_log.txt`):
   - Logs file processing details and errors.

---

### Advanced Features

#### Snapshot Management
- Save snapshots of your project tree and reload them later.
- Export filtered views for team sharing.

#### Copy Tree as Text
- Generate a clean ASCII representation:
  ```plaintext
  Project Tools Runner/
  ├── file_loader.py
  ├── tool_runner_ui.py
  ├── requirements.txt
  └── Tools_Outputs/
      ├── loaded_files_output.txt
      └── project_structure.json
  ```

#### Console Output
![Console Output](images/Screenshot_Project_Tools_Runner_8_Console.png)

Monitor real-time updates:
- File processing status.
- Logs for excluded/skipped files.
- Errors or warnings.

---

## Web App (Browser, Privacy-First)

The `webapp/` directory provides a browser-based front end that runs the **exact same
Python tools** as the desktop app — no install of Tkinter or a local display required.
You open a page, pick a folder, and the analysis runs **entirely inside your browser
tab**. No project files are ever uploaded to or stored on a server.

### How It Works

The web app runs the real `FileLoaderTool` and `ProjectStructureTool` in the browser via
[Pyodide](https://pyodide.org) (CPython compiled to WebAssembly):

- `webapp/app.py` is a **thin static host**. It serves the single-page UI and, via
  `/core/<name>`, the unchanged core `.py` modules so the browser can load them into
  Pyodide. It performs **no** file processing and never receives your files.
- The browser builds an in-memory virtual filesystem from the folder you pick, runs the
  tools inside Pyodide, and produces the same outputs (concatenated text, structure JSON)
  as in-browser downloads. Because it uses the tools' own save logic, the output is
  byte-for-byte identical to the desktop app.

The UI mirrors the desktop feature set: an interactive structure tree, name search,
file-type filter, column toggles (size / created / modified), show-excluded-dirs toggle,
ASCII export, snapshot save/load, persistent settings, a progress bar, and a cancel button.

### Running the Web App

Sync dependencies and start the static host (any platform):

```bash
uv sync
uv run python webapp/app.py
# pip fallback: pip install -r requirements.txt && python webapp/app.py
```

Then open <http://localhost:5000> in your browser. The host and port honor the `HOST` and
`PORT` environment variables and default to `0.0.0.0:5000`:

```bash
HOST=127.0.0.1 PORT=8080 uv run python webapp/app.py
```

<a id="web-interface-guide"></a>
### Web Interface Guide

The browser UI mirrors the desktop feature set, organized into a left **control panel**
and a right **results area** with three tabs: **Structure**, **Concatenated files**, and
**Logs**.

> **Note:** The Main Interface screenshot below is a real capture of the running app.
> The remaining three (tree view, toolbar, and logs) require a loaded project and are
> placeholders for now — capture your own from a running web app
> (<http://localhost:5000>) and drop them into `images/` using the file names referenced
> below to replace them.

<a id="main-interface-web"></a>
#### Main Interface

![Web App — Main Interface](images/Screenshot_Web_1_Main.png)
*The web app's landing screen: the control panel on the left and the empty Structure tab on the right.*

The left control panel offers:
- **Source selection**: choose **Local folder** (pick a folder on your machine) or
  **Public Git URL** (clone a public repo client-side). See [Source Modes](#source-modes).
- **Tool selection**: run **Project structure**, **File loader (concatenate)**, or both.
- **Excludes configuration**: toggle the default excludes and edit the comma-separated
  list of directory names to skip (e.g., `.git`, `venv`, `node_modules`).
- **Run controls**: a **Run Tools** button, a **Cancel** button, and a progress bar for
  long scans.

<a id="project-tree-view-web"></a>
#### Project Tree View

![Web App — Project Tree View](images/Screenshot_Web_2_Tree.png)
*Placeholder — the Structure tab with the populated, multi-column tree.*

The **Structure** tab shows the same interactive tree as the desktop app:
- Expandable folders with **file counts** for each directory.
- Metadata columns for **size**, **created**, and **modified** timestamps.
- **Sticky column headers** that stay visible while you scroll.

<a id="toolbar-controls-web"></a>
#### Toolbar Controls

![Web App — Toolbar Controls](images/Screenshot_Web_3_Controls.png)
*Placeholder — the Structure tab toolbar (search, filters, toggles, and export buttons).*

The toolbar above the tree provides:
- **Search by name** and **filter by file type** in real time.
- **Column toggles**: show or hide **Size**, **Created**, and **Modified**.
- **Show excluded dirs**: include or hide directories matched by the excludes list.
- **Expand all** / **Collapse all** for quick navigation.
- **Copy ASCII**: copy the visible tree as a clean ASCII diagram.
- **Download JSON**: download just the structure as `project_structure.json`.
- **Save snapshot** / **Load snapshot**: save a reloadable bundle (structure + file
  output + excludes) and reopen it later.

All controls have hover hints, and your column/filter preferences persist between
sessions.

<a id="concatenated-files-and-logs-web"></a>
#### Concatenated Files and Logs

![Web App — Concatenated Files and Logs](images/Screenshot_Web_4_Logs.png)
*Placeholder — the Concatenated files and Logs tabs.*

- The **Concatenated files** tab shows the combined text output (the same content the
  File loader writes), ready to copy or download.
- The **Logs** tab streams real-time processing details — files processed, files
  skipped or excluded, and any errors — mirroring the desktop console.

### Source Modes

The web app can analyze a project from two sources:

- **Local folder** — pick a folder on your computer. Files are read locally in the tab and
  never leave your machine.
- **Public Git URL** — clone a **public** repository **entirely client-side** over HTTPS.
  No token or login is used (public repos only). Because browsers cannot speak the raw git
  protocol, the fetch is relayed through a configurable **CORS proxy** (defaults to the
  public `https://cors.isomorphic-git.org`, editable under "Advanced"). The clone lives in
  an in-memory filesystem and is discarded when you leave the page.

### Privacy Guarantees

- Your local files are **never uploaded** — all processing happens in your browser tab.
- The server is a static host only; it never reads, stores, or proxies your project files.
- Outputs are generated in-browser as downloads, so they stay on your machine.

---

## MCP Server (AI Agent Access)

In addition to the desktop UI, the same core file-reading tools can be exposed to an
AI assistant (such as Claude Desktop or an MCP-capable IDE agent) through a local
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server.

### What It Is

The MCP server (`mcp_server.py`) lets an AI agent call the project's tools directly —
"show me the structure," "read this file," "concatenate this folder" — instead of you
copy-pasting files into a chat. It:

- Runs **entirely on your own machine** as a local program. There is no hosting, no
  account, and no login.
- Communicates with the AI client over **stdio** (a direct pipe between the two
  programs). Nothing is sent over the network and **no data leaves your computer**.
- Is **strictly read-only** — it can list and read files, but never write, delete, or
  execute anything.

It reuses the exact same `FileLoaderTool` and `ProjectStructureTool` as the desktop and
web apps, so the results are identical.

<a id="mcp-installation"></a>
### Installation

The MCP server requires **Python 3.10+** (for the `mcp` SDK), pulled in via the optional
`mcp` extra. The core tools themselves still run on Python 3.9+.

```bash
uv sync --extra mcp
# pip fallback: pip install -r requirements.txt -r requirements-mcp.txt
```

### Running the Server

Point the server at one or more directories it is allowed to read with `--root`
(repeatable). You normally do **not** run this command yourself — your AI client launches
it for you (see the next section) — but you can run it directly to verify it starts:

```bash
uv run python mcp_server.py --root /path/to/your/project
```

Alternatively, set the allowed roots via an environment variable:

```bash
TOOLS_MCP_ALLOWED_ROOTS=/path/to/project uv run python mcp_server.py
```

Useful optional flags: `--exclude NAME` (extra directory name to skip, repeatable),
`--max-files`, `--max-total-bytes`, `--max-file-bytes`, and `--max-depth` to tune the
safety caps. Run `uv run python mcp_server.py --help` for the full list.

### Connecting an AI Client

Your AI client starts the server for you; you just tell it the command to run. For
**Claude Desktop**, add an entry to its `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "project-tools": {
      "command": "python",
      "args": [
        "/absolute/path/to/mcp_server.py",
        "--root",
        "/absolute/path/to/your/project"
      ]
    }
  }
}
```

Use **absolute paths** for both `mcp_server.py` and each `--root`. Restart the client,
and the tools below will appear automatically. Other MCP-capable clients (Cursor,
Windsurf, VS Code agents, etc.) use the same `command` / `args` shape in their own
config location.

> **Using uv?** Point the client at uv so it runs inside the locked environment —
> set `"command": "uv"` with `"args": ["run", "python", "mcp_server.py", "--root", "/absolute/path/to/your/project"]`
> and add `"cwd": "/absolute/path/to/AI-Dev-Kit"` so uv finds the project.

### Available Tools

| Tool | Description |
|------|-------------|
| `list_allowed_roots` | Returns the directories the server is permitted to read. |
| `project_structure`  | Builds the nested folder/file tree (with metadata) for an allowed path. |
| `load_directory`     | Concatenates the text files in an allowed directory. |
| `read_file`          | Returns the contents of a single allowed file. |

### Security Model

Safety is enforced by `mcp_security.py`, independent of the MCP SDK:

- **Allowed-roots jail** — the server can only touch paths inside the directories you
  passed with `--root`. It resolves real paths to block `../` traversal and symlink
  escapes that would point outside those roots.
- **Secret-aware excludes** — sensitive files such as `.env`, `*.pem`, and private keys
  are never returned, even when explicitly requested.
- **Size and depth caps** — limits on file count, total bytes, per-file bytes, and
  directory depth prevent runaway reads.
- **Read-only** — no write, delete, or execute capability exists in any tool.

---

## Technical Details

## File Processing

A short overview of how files are scanned and processed: the tool walks the project tree, detects text vs binary files, extracts metadata, and aggregates results into output files and JSON snapshots.

## Tree Visualization

This section describes the tree visualization output: a multi-column, interactive view that displays directory structure along with file metadata (size, created, modified) and supports filtering and snapshots.

### Workflow Diagrams

#### File Processing Workflow
```mermaid

graph TD
    A[Start Scan] --> B[Initialize Directory Walk]
    B --> C{Is Entry a Directory?}
    C -->|Yes| D[Recursively Process Subdirectory]
    C -->|No| E{Is Entry a File?}
    E -->|Yes| F[Check File Type]
    F --> G{Text or Binary?}
    G -->|Text| H[Process and Collect Metadata]
    G -->|Binary| I[Log Skipped File]
    E -->|No| J[Log Exclusion]
    D --> K[Merge Subdirectory Data]
    H --> K
    I --> K
    J --> K
    K --> L{More Entries?}
    L -->|Yes| B
    L -->|No| M[Save Results and Finish]

```
![File Processing Workflow](images/Screenshot_Project_Tools_Runner_10_Workflow.png)

---

## FAQ and Troubleshooting

### Q: Why is the tree view empty?
- Check if the selected directory contains files.
- Verify that excluded folders (e.g., `venv`, `.git`) are toggled.

### Q: I see "Permission Denied" errors in the console. What should I do?
- Ensure you have read permissions for all files in the project directory.
- Run the app with administrative privileges if needed.

### Q: Can I include binary files in the concatenated output?
- No, binary files are automatically skipped to prevent encoding issues.

---

## Contributing

We welcome contributions! To contribute:
1. Fork the repository.
2. Create a new branch.
3. Implement your feature or fix.
4. Submit a pull request.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**Author**: [Siddharth Venkumahnati](https://github.com/sidbetatester)  
**Project**: Part of the [AI-Dev-Kit](https://github.com/sidbetatester/AI-Dev-Kit)

> **Project Tools Runner**: Simplifying project management for developers and technical writers. 

---
