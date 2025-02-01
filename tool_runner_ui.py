"""
tool_runner_ui.py

A comprehensive Tkinter-based GUI for:
1) Concatenating project files (FileLoaderTool),
2) Building a JSON project structure (ProjectStructureTool),
3) Displaying that structure in a multi-column TreeView with ASCII
   indentation for the folder/file names,
4) Toggling columns (Size, Created, Modified) on/off,
5) Searching, filtering (by file extension), and snapshotting,
6) Copying the tree as ASCII (only for columns currently visible),
7) Toggling the tree and console panes,
8) Ensuring subfolder names appear only once (no duplication) in both
   the on-screen UI and the copied ASCII,
9) Retaining the real root folder name at the top,
10) Displaying file counts for each folder in the "Size" column,
11) Providing a two-click "Collapse All" button that toggles between fully
    collapsing to root vs. partially collapsing to show only top-level folders,
12) Preserving the current open/closed state when toggling “Show Excluded Dirs,”
    so the tree doesn’t collapse to root.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import sys
import json
from typing import Any, Dict, List, Optional, Tuple, Union

from file_loader_tool import FileLoaderTool
from project_structure_tool import ProjectStructureTool


################################################
# Tooltip System
################################################
class ToolTip:
    """
    A small tooltip class for Tkinter widgets, creating a little popup window
    near the widget on hover.
    """
    def __init__(self, widget: tk.Widget, text: str = "") -> None:
        """
        Initialize the tooltip.

        Args:
            widget: The Tk widget to attach the tooltip to.
            text: The text displayed by the tooltip.
        """
        self.widget = widget
        self.text = text
        self.tip_window: Optional[tk.Toplevel] = None
        self.widget.bind("<Enter>", self._show_tip)
        self.widget.bind("<Leave>", self._hide_tip)

    def _show_tip(self, event: Optional[tk.Event] = None) -> None:
        """Show the tooltip if not already visible."""
        if self.tip_window or not self.text:
            return
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)

        x_left = self.widget.winfo_rootx() + 20
        y_top = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        tw.wm_geometry(f"+{x_left}+{y_top}")

        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("tahoma", 8, "normal")
        )
        label.pack(ipadx=4, ipady=2)

    def _hide_tip(self, event: Optional[tk.Event] = None) -> None:
        """Hide the tooltip window."""
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def create_tooltip(widget: tk.Widget, text: str) -> 'ToolTip':
    """
    Convenience function to attach a ToolTip to a widget with given text.

    Args:
        widget: The Tk widget to attach the tooltip to.
        text: The tooltip text.

    Returns:
        The created ToolTip object.
    """
    return ToolTip(widget, text)


################################################
# Text Redirector for console
################################################
class TextRedirector:
    """
    A class to redirect stdout (print statements) into a Tkinter ScrolledText widget.
    """
    def __init__(self, widget: scrolledtext.ScrolledText, tag: str = "stdout") -> None:
        """
        Initialize the redirector.

        Args:
            widget: The ScrolledText widget to write stdout text to.
            tag: A tag name for styling (unused by default).
        """
        self.widget = widget
        self.tag = tag

    def write(self, string: str) -> None:
        """
        Write the given string into the scrolled text widget.
        """
        self.widget.configure(state="normal")
        self.widget.insert("end", string, (self.tag,))
        self.widget.configure(state="disabled")
        self.widget.see("end")

    def flush(self) -> None:
        """Required for file-like objects; no-op here."""
        pass


################################################
# WrapFrame for auto-wrapping toolbar buttons
################################################
class WrapFrame(tk.Frame):
    """
    A custom frame that flows (wraps) its children onto new lines if the window is too narrow.
    """
    def __init__(self, parent: tk.Widget, margin: int = 5, **kwargs) -> None:
        """
        Args:
            parent: The parent widget for this frame.
            margin: Spacing between children (in pixels).
            **kwargs: Additional kwargs passed to the tk.Frame initializer.
        """
        super().__init__(parent, **kwargs)
        self.margin = margin
        self._items: List[tk.Widget] = []
        self.bind("<Configure>", self._on_configure)

    def add_widget(self, widget: tk.Widget) -> None:
        """
        Add a child widget to this wrap frame. We'll place it ourselves in flow layout.
        """
        self._items.append(widget)
        widget.place(x=0, y=0)

    def _on_configure(self, event: tk.Event) -> None:
        """
        Reflow child widgets whenever the frame is resized.
        """
        x, y = self.margin, self.margin
        line_height = 0
        for child in self._items:
            reqw = child.winfo_reqwidth()
            reqh = child.winfo_reqheight()
            if x + reqw + self.margin > event.width:
                x = self.margin
                y += line_height + self.margin
                line_height = 0
            child.place(x=x, y=y)
            x += reqw + self.margin
            line_height = max(line_height, reqh)
        self.config(height=y + line_height + self.margin)


################################################
# Main UI
################################################
class ToolRunnerUI(tk.Tk):
    """
    A comprehensive Tkinter GUI providing:

    - Directory selection for a project root and output folder,
    - Running FileLoaderTool (concatenate text files),
    - Running ProjectStructureTool (build JSON of project),
    - Displaying the project in a TreeView with ASCII indentation in #0 column,
    - Additional columns: size, created, modified,
    - Checkbuttons to show/hide columns,
    - Searching, file-type filtering, toggling tree/console panes,
    - Snapshot saving/loading,
    - Copying the tree as ASCII (respecting visible columns),
    - Real root folder name at top, no subfolder duplication,
    - Displaying file counts for each folder in the Size column,
    - And a two-click "Collapse All" button that toggles between fully
      collapsing to root vs. partially collapsing to show only top-level folders,
    - While preserving the current open/closed state if "Show Excluded Dirs" is toggled.
    """

    def __init__(self) -> None:
        """
        Initialize the ToolRunnerUI, creating all widgets, styles, and logic.
        """
        super().__init__()
        self.title("Project Tools Runner")
        self.geometry("900x600")

        # Track hidden states for toggling
        self.tree_hidden = False
        self.console_hidden = False
        self.last_tree_sash: Optional[int] = None
        self.last_console_sash: Optional[int] = None

        # Additional state to handle the two-click "Collapse All" logic
        self.collapse_mode = 0  # 0 => next time do full collapse, 1 => next time do partial

        # Configure TTK styles for various colored buttons
        style = ttk.Style(self)
        style.configure("Run.TButton",        background="lightgreen",  foreground="black")
        style.configure("Clear.TButton",      background="lightcoral",  foreground="black")
        style.configure("HideTree.TButton",   background="white",       foreground="black")
        style.configure("HideConsole.TButton",background="black",       foreground="green")
        style.configure("About.TButton",      background="white",       foreground="blue")
        style.configure("TreeTool.TButton",   background="lightblue",   foreground="black")

        # Main frame
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1) Directory selection
        ttk.Label(self.main_frame, text="Project Root:").grid(row=0, column=0, sticky=tk.W)
        self.dir_entry = ttk.Entry(self.main_frame, width=50)
        self.dir_entry.grid(row=0, column=1, sticky=tk.EW)
        btn_root = ttk.Button(self.main_frame, text="Browse...", command=self.select_directory, width=13)
        btn_root.grid(row=0, column=2)

        create_tooltip(self.dir_entry, "Path to your top-level project folder.")
        create_tooltip(btn_root, "Select the project root directory.")

        ttk.Label(self.main_frame, text="Output Directory:").grid(row=1, column=0, sticky=tk.W)
        self.output_dir_entry = ttk.Entry(self.main_frame, width=50)
        self.output_dir_entry.grid(row=1, column=1, sticky=tk.EW)
        self.output_dir_entry.insert(0, "Tools_Outputs")
        btn_out = ttk.Button(self.main_frame, text="Browse...", command=self.select_output_dir, width=13)
        btn_out.grid(row=1, column=2)

        create_tooltip(self.output_dir_entry, "Where logs, concatenated files, and JSON structures go.")
        create_tooltip(btn_out, "Select the output directory.")

        # 2) Tool selection
        self.tool_vars = {
            'file_loader': tk.BooleanVar(value=True),
            'project_structure': tk.BooleanVar(value=True)
        }
        ttk.Label(self.main_frame, text="Select Tools:").grid(row=2, column=0, sticky=tk.W)
        tools_frame = ttk.Frame(self.main_frame)
        tools_frame.grid(row=2, column=1, sticky=tk.W)

        chk_loader = ttk.Checkbutton(tools_frame, text="File Loader", variable=self.tool_vars['file_loader'])
        chk_struct = ttk.Checkbutton(tools_frame, text="Project Structure", variable=self.tool_vars['project_structure'])
        chk_loader.pack(side=tk.LEFT, padx=(0,10))
        chk_struct.pack(side=tk.LEFT, padx=(0,10))

        create_tooltip(chk_loader, "Concatenate all project files into a single text file.")
        create_tooltip(chk_struct, "Generate & display a JSON project structure in an ASCII tree.")

        # Right side: run/clear/hide/about
        action_buttons_frame = ttk.Frame(self.main_frame)
        action_buttons_frame.grid(row=2, column=2, rowspan=4, sticky=tk.NE)

        btn_run = ttk.Button(
            action_buttons_frame,
            text="Run Tools",
            command=self.run_tools,
            width=13,
            style="Run.TButton"
        )
        btn_run.pack(anchor="e", pady=(0,5))
        create_tooltip(btn_run, "Generate the concatenated file and/or JSON structure.")

        btn_clear = ttk.Button(
            action_buttons_frame,
            text="Clear Console",
            command=self.clear_console,
            width=13,
            style="Clear.TButton"
        )
        btn_clear.pack(anchor="e", pady=(0,5))
        create_tooltip(btn_clear, "Clears the console output area.")

        btn_hide_tree = ttk.Button(
            action_buttons_frame,
            text="Hide Tree",
            command=self.toggle_tree_pane,
            width=13,
            style="HideTree.TButton"
        )
        btn_hide_tree.pack(anchor="e", pady=(0,5))
        create_tooltip(btn_hide_tree, "Hide the project tree pane (click again to restore).")

        btn_hide_console = ttk.Button(
            action_buttons_frame,
            text="Hide Console",
            command=self.toggle_console_pane,
            width=13,
            style="HideConsole.TButton"
        )
        btn_hide_console.pack(anchor="e", pady=(0,5))
        create_tooltip(btn_hide_console, "Hide the console pane (click again to restore).")

        btn_about = ttk.Button(
            action_buttons_frame,
            text="About",
            command=self.show_about,
            width=13,
            style="About.TButton"
        )
        btn_about.pack(anchor="e", pady=(0,5))
        create_tooltip(btn_about, "Information about this tool, author, and license.")

        # 3) File/Structure/Log outputs
        ttk.Label(self.main_frame, text="File Loader Output:").grid(row=3, column=0, sticky=tk.W)
        self.file_loader_output = ttk.Entry(self.main_frame, width=50)
        self.file_loader_output.grid(row=3, column=1, sticky=tk.EW)
        self.file_loader_output.insert(0, "loaded_files_output.txt")

        ttk.Label(self.main_frame, text="Structure Output:").grid(row=4, column=0, sticky=tk.W)
        self.structure_output = ttk.Entry(self.main_frame, width=50)
        self.structure_output.grid(row=4, column=1, sticky=tk.EW)
        self.structure_output.insert(0, "project_structure.json")

        ttk.Label(self.main_frame, text="Log File:").grid(row=5, column=0, sticky=tk.W)
        self.log_file_output = ttk.Entry(self.main_frame, width=50)
        self.log_file_output.grid(row=5, column=1, sticky=tk.EW)
        self.log_file_output.insert(0, "file_loader_log.txt")

        # 4) PanedWindow => top=tree_panel, bottom=console_panel
        self.paned = ttk.Panedwindow(self.main_frame, orient=tk.VERTICAL)
        self.paned.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        self.tree_panel = ttk.Frame(self.paned)
        self.paned.add(self.tree_panel, weight=3)

        self.console_panel = ttk.Frame(self.paned)
        self.paned.add(self.console_panel, weight=1)

        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(7, weight=1)

        # 5) Top Pane: Tree label
        self.tree_label = ttk.Label(self.tree_panel, text="Project Tree", font=("Arial", 12, "bold"))
        self.tree_label.pack(side=tk.TOP, anchor="w", padx=5, pady=(5,0))

        # A sub-frame for controlling which columns are visible
        self.column_frame = ttk.Frame(self.tree_panel)
        self.column_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0,5))

        self.col_vars = {
            "size": tk.BooleanVar(value=True),
            "created": tk.BooleanVar(value=True),
            "modified": tk.BooleanVar(value=True)
        }

        ttk.Label(self.column_frame, text="Columns: ").pack(side=tk.LEFT)
        chk_size = ttk.Checkbutton(
            self.column_frame,
            text="Size",
            variable=self.col_vars["size"],
            command=self.update_displaycolumns
        )
        chk_size.pack(side=tk.LEFT, padx=(5,0))

        chk_created = ttk.Checkbutton(
            self.column_frame,
            text="Created",
            variable=self.col_vars["created"],
            command=self.update_displaycolumns
        )
        chk_created.pack(side=tk.LEFT, padx=(5,0))

        chk_modified = ttk.Checkbutton(
            self.column_frame,
            text="Modified",
            variable=self.col_vars["modified"],
            command=self.update_displaycolumns
        )
        chk_modified.pack(side=tk.LEFT, padx=(5,0))

        # Tree toolbar
        self.tree_toolbar = WrapFrame(self.tree_panel, margin=5)
        self.tree_toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        lbl_search = ttk.Label(self.tree_toolbar, text="Search:")
        self.tree_toolbar.add_widget(lbl_search)

        self.search_entry = ttk.Entry(self.tree_toolbar, width=15)
        self.search_entry.bind('<KeyRelease>', self.search_tree)
        self.tree_toolbar.add_widget(self.search_entry)

        lbl_filetypes = ttk.Label(self.tree_toolbar, text="File Types:")
        self.tree_toolbar.add_widget(lbl_filetypes)

        self.file_types = ttk.Combobox(self.tree_toolbar, values=['All', '.py', '.json', '.txt', '.md'], width=5)
        self.file_types.set('All')
        self.file_types.bind('<<ComboboxSelected>>', self.filter_by_type)
        self.tree_toolbar.add_widget(self.file_types)

        self.show_excluded = tk.BooleanVar(value=True)
        # Instead of calling refresh_tree() directly, we call a method that preserves expansions
        chk_exclude = ttk.Checkbutton(
            self.tree_toolbar,
            text="Show Excluded Dirs",
            variable=self.show_excluded,
            command=self.on_toggle_excluded
        )
        self.tree_toolbar.add_widget(chk_exclude)

        btn_expand = ttk.Button(
            self.tree_toolbar,
            text="Expand All",
            command=lambda: self.toggle_tree_view(True),
            style="TreeTool.TButton"
        )
        self.tree_toolbar.add_widget(btn_expand)

        # The "Collapse All" button is now tied to on_collapse_all_clicked,
        # toggling between full collapse & partial collapse
        btn_collapse = ttk.Button(
            self.tree_toolbar,
            text="Collapse All",
            command=self.on_collapse_all_clicked,
            style="TreeTool.TButton"
        )
        self.tree_toolbar.add_widget(btn_collapse)

        btn_save_snap = ttk.Button(
            self.tree_toolbar,
            text="Save Snapshot",
            command=self.save_snapshot,
            style="TreeTool.TButton"
        )
        self.tree_toolbar.add_widget(btn_save_snap)

        btn_load_snap = ttk.Button(
            self.tree_toolbar,
            text="Load Snapshot",
            command=self.load_snapshot,
            style="TreeTool.TButton"
        )
        self.tree_toolbar.add_widget(btn_load_snap)

        btn_copy_tree = ttk.Button(
            self.tree_toolbar,
            text="Copy Tree as Text",
            command=self.copy_ascii_tree,
            style="TreeTool.TButton"
        )
        self.tree_toolbar.add_widget(btn_copy_tree)

        # Tree area (multi-column)
        self.tree_frame = ttk.Frame(self.tree_panel)
        self.tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            self.tree_frame,
            columns=("size", "created", "modified"),
            show="tree headings",
            selectmode='browse',
            padding=5
        )

        style.configure(
            "Treeview",
            background="white",
            fieldbackground="white",
            font=("Consolas", 14)
        )

        # Column configs
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.column("#0", width=350, anchor="w", stretch=True)

        self.tree.heading("size", text="Size", anchor="center")
        self.tree.column("size", width=100, anchor="e", stretch=False)

        self.tree.heading("created", text="Created", anchor="center")
        self.tree.column("created", width=160, anchor="center", stretch=False)

        self.tree.heading("modified", text="Modified", anchor="center")
        self.tree.column("modified", width=160, anchor="center", stretch=False)

        self.tree.tag_configure('folder', font=('Consolas', 14, 'bold'), foreground='black')
        self.tree.tag_configure('file', font=('Consolas', 14), foreground='#0066cc')
        self.tree.tag_configure('highlight', background='yellow', font=('Consolas', 14, 'bold'))

        vsb = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        hsb.grid(row=1, column=0, sticky=tk.EW)
        self.tree_frame.columnconfigure(0, weight=1)
        self.tree_frame.rowconfigure(0, weight=1)

        # Initially show all columns
        self.update_displaycolumns()

        # 6) Console Panel
        self.console_label = ttk.Label(self.console_panel, text="Console Output", font=("Arial", 12, "bold"))
        self.console_label.pack(side=tk.TOP, anchor="w", padx=5, pady=(5,0))

        self.console = scrolledtext.ScrolledText(self.console_panel, height=10)
        self.console.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.console.configure(background="black", foreground="green", insertbackground="green")

        # Redirect stdout to the console
        self.original_stdout = sys.stdout
        sys.stdout = TextRedirector(self.console, "stdout")

    def __del__(self) -> None:
        """
        Restore original stdout upon destruction.
        """
        sys.stdout = self.original_stdout

    ################################################
    # Show/Hide Columns
    ################################################
    def update_displaycolumns(self) -> None:
        """
        Read the checkbutton states (size/created/modified) and update
        self.tree["displaycolumns"] to show or hide the respective columns.
        """
        cols: List[str] = []
        if self.col_vars["size"].get():
            cols.append("size")
        if self.col_vars["created"].get():
            cols.append("created")
        if self.col_vars["modified"].get():
            cols.append("modified")
        self.tree["displaycolumns"] = cols

    ################################################
    # Two-click "Collapse All" logic
    ################################################
    def on_collapse_all_clicked(self) -> None:
        """
        When "Collapse All" is clicked:
        - If collapse_mode == 0, we do a full collapse (close everything to the root).
        - If collapse_mode == 1, we do a partial collapse (only show top-level children, excluding files).
        Then we toggle collapse_mode for the next click.
        """
        if self.collapse_mode == 0:
            self._collapse_all()
            self.collapse_mode = 1
        else:
            self._collapse_to_level_1()
            self.collapse_mode = 0

    def _collapse_all(self) -> None:
        """
        Fully collapse everything, i.e. close all items.
        """
        self.toggle_tree_view(False)

    def _collapse_to_level_1(self) -> None:
        """
        Collapse everything except keep only top-level folders visible.
        Root-level files are also hidden for partial collapse.
        """
        # Step 1: close everything
        self.toggle_tree_view(False)
        # Step 2: reopen each child if it's a folder
        for child in self.tree.get_children(''):
            # If it's a folder, re-open it to see if it has sub-nodes
            # but keep sub-nodes collapsed
            if 'folder' in self.tree.item(child, 'tags'):
                self.tree.item(child, open=True)
            else:
                # If it's a file, detach or remain collapsed
                # Let's detach so that top-level file is not visible
                self.tree.detach(child)

    ################################################
    # Toggle Tree/Console Panes
    ################################################
    def toggle_tree_pane(self) -> None:
        """
        Hide or show the top (tree) pane by adjusting the sash position
        of the paned window.
        """
        if not self.tree_hidden:
            self.last_tree_sash = self.paned.sashpos(0)
            self.paned.sashpos(0, 0)
            self.tree_hidden = True
        else:
            if self.last_tree_sash is None:
                total_height = self.paned.winfo_height()
                self.paned.sashpos(0, total_height // 2)
            else:
                self.paned.sashpos(0, self.last_tree_sash)
            self.tree_hidden = False

    def toggle_console_pane(self) -> None:
        """
        Hide or show the bottom (console) pane similarly.
        """
        if not self.console_hidden:
            self.last_console_sash = self.paned.sashpos(0)
            total_height = self.paned.winfo_height()
            self.paned.sashpos(0, total_height)
            self.console_hidden = True
        else:
            if self.last_console_sash is None:
                total_height = self.paned.winfo_height()
                self.paned.sashpos(0, total_height // 2)
            else:
                self.paned.sashpos(0, self.last_console_sash)
            self.console_hidden = False

    ################################################
    # Directory selection
    ################################################
    def select_directory(self) -> None:
        """
        Prompt the user to choose a project root directory
        and store it in self.dir_entry.
        """
        directory = filedialog.askdirectory()
        if directory:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, directory)

    def select_output_dir(self) -> None:
        """
        Prompt the user to choose an output directory
        and store it in self.output_dir_entry.
        """
        directory = filedialog.askdirectory()
        if directory:
            self.output_dir_entry.delete(0, tk.END)
            self.output_dir_entry.insert(0, directory)

    ################################################
    # Running Tools
    ################################################
    def run_tools(self) -> None:
        """
        Run whichever tools (File Loader, Project Structure) are selected,
        using the directory paths specified in dir_entry/output_dir_entry.
        """
        project_root = self.dir_entry.get()
        output_dir = self.output_dir_entry.get()

        if not project_root or not os.path.isdir(project_root):
            print("Error: Invalid project directory")
            return

        os.makedirs(output_dir, exist_ok=True)

        try:
            # 1) File Loader
            if self.tool_vars['file_loader'].get():
                file_loader_output = os.path.join(output_dir, self.file_loader_output.get())
                loader = FileLoaderTool(project_root)
                files_dict = loader.load_files_in_directory(project_root)
                loader.save_file_contents(files_dict, file_loader_output)
                loader.save_log(os.path.join(output_dir, self.log_file_output.get()))
                print(f"File loader output saved to {file_loader_output}")

            # 2) Project Structure
            if self.tool_vars['project_structure'].get():
                structure_output = os.path.join(output_dir, self.structure_output.get())
                structure_tool = ProjectStructureTool(project_root)
                structure_tool.build_project_structure()
                structure_tool.save_project_structure(structure_output)
                print(f"Project structure saved to {structure_output}")
                self.load_and_display_structure(structure_output)

            print("Operation completed successfully\n")
        except Exception as e:
            print(f"Error: {str(e)}")

    def clear_console(self) -> None:
        """
        Clear the console text area.
        """
        self.console.configure(state="normal")
        self.console.delete(1.0, tk.END)
        self.console.configure(state="disabled")

    ################################################
    # Build & Display ASCII Tree (with real root name + folder file counts)
    ################################################
    def load_and_display_structure(self, json_file: str) -> None:
        """
        Read the JSON file to get the project structure dict,
        handle the top-level folder name(s), then call _build_tree_ascii
        (once per root) to populate the TreeView with ASCII indentation.
        """
        # Step 1: store open states so we can restore them after re-building
        expand_states = self._remember_open_states()

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                structure: Dict[str, Any] = json.load(f)

            # Clear old tree first
            self.tree.delete(*self.tree.get_children())

            # If there's exactly one top-level key, treat that as the root folder
            top_keys = sorted(structure.keys())
            if len(top_keys) == 1:
                root_name = top_keys[0]
                root_data = structure[root_name]
                self._build_tree_ascii("", root_data, [], root_name)
            else:
                # multiple top-level folders
                for key in top_keys:
                    self._build_tree_ascii("", structure[key], [], key)

            print("Project structure loaded in UI")

        except Exception as e:
            print(f"Error loading structure: {str(e)}")
            return

        # Step 2: restore expansions
        self._restore_open_states(expand_states)

    def _build_tree_ascii(
        self,
        parent_node: str,
        data: Dict[str, Any],
        ancestors: List[bool],
        folder_name: str
    ) -> None:
        """
        Insert exactly one node for 'folder_name', then recursively
        insert subfolders/files, ensuring we do not duplicate subfolder names.
        Also, for folders, we display "N files" in the 'Size' column,
        where N is the total number of files in that folder's subtree.

        Args:
            parent_node: ID of the parent node in the TreeView,
                         or "" if top-level.
            data: The dictionary describing this folder's "subfolders" and "files".
            ancestors: A list of bools indicating whether each ancestor is the last
                       child at its level, for building ASCII prefix.
            folder_name: The name of this folder to display.
        """
        # Build ASCII prefix for this folder's line
        prefix_parts: List[str] = []
        for ancestor_last in ancestors[:-1]:
            prefix_parts.append("    " if ancestor_last else "│   ")
        if ancestors:
            prefix_parts.append("└── " if ancestors[-1] else "├── ")
        ascii_prefix = "".join(prefix_parts)

        # For folder: count total files in sub-tree
        num_files = self._count_files_in_tree(data)
        folder_id = self.tree.insert(
            parent_node,
            "end",
            text=f"{ascii_prefix}{folder_name}",
            values=(f"{num_files} files", "", ""),  # place file count in 'size' column
            tags=('folder',),
            open=False
        )

        # Extract subfolders, files
        subfolders: Dict[str, Any] = data.get("subfolders", {})
        files: List[Union[str, Dict[str, Any]]] = data.get("files", [])

        # Build a list of children for sorting
        children: List[Tuple[Any, str, Optional[Dict[str, Any]]]] = []

        # subfolders => (sf_name, "folder", subfolder_data)
        for sf_name, sf_data in subfolders.items():
            if self._should_show_dir(sf_name):
                children.append((sf_name, "folder", sf_data))

        # files => either "file" (just a string) or "fileobj" (a dict with name, size, etc.)
        for f_item in files:
            if isinstance(f_item, dict) and "name" in f_item:
                children.append((f_item, "fileobj", None))
            else:
                children.append((f_item, "file", None))

        def get_sort_key(ch: Tuple[Any, str, Optional[Dict[str, Any]]]) -> str:
            name, kind, _ = ch
            if kind == "folder":
                return str(name).lower()
            elif kind == "fileobj":
                return str(name["name"]).lower()
            else:
                return str(name).lower()

        children.sort(key=get_sort_key)

        # Insert each subfolder/file
        for i, (child, kind, subdata) in enumerate(children):
            is_last_child = (i == len(children) - 1)

            if kind == "folder":
                # Recursively call _build_tree_ascii for the subfolder
                self._build_tree_ascii(
                    parent_node=folder_id,
                    data=subdata,
                    ancestors=ancestors + [is_last_child],
                    folder_name=str(child)
                )

            elif kind == "fileobj":
                # It's a dict with { name, size, created, modified } etc.
                fname: str = str(child.get("name", "unknown"))
                fsize = child.get("size", None)
                fcreated = child.get("created", None)
                fmod = child.get("modified", None)

                child_prefix_parts: List[str] = []
                for ancestor_last in ancestors[:-1]:
                    child_prefix_parts.append("    " if ancestor_last else "│   ")
                if ancestors:
                    child_prefix_parts.append("└── " if ancestors[-1] and is_last_child else "├── ")
                else:
                    child_prefix_parts.append("└── " if is_last_child else "├── ")
                ascii_child_prefix = "".join(child_prefix_parts)

                file_text = f"{ascii_child_prefix}{fname}"
                size_str = f"{fsize} bytes" if fsize else ""
                created_str = fcreated or ""
                mod_str = fmod or ""

                self.tree.insert(
                    folder_id,
                    "end",
                    text=file_text,
                    values=(size_str, created_str, mod_str),
                    tags=('file',)
                )

            else:
                # Plain string for a file
                child_prefix_parts: List[str] = []
                for ancestor_last in ancestors[:-1]:
                    child_prefix_parts.append("    " if ancestor_last else "│   ")
                if ancestors:
                    child_prefix_parts.append("└── " if ancestors[-1] and is_last_child else "├── ")
                else:
                    child_prefix_parts.append("└── " if is_last_child else "├── ")
                ascii_child_prefix = "".join(child_prefix_parts)

                fname_str = f"{ascii_child_prefix}{child}"
                self.tree.insert(
                    folder_id,
                    "end",
                    text=fname_str,
                    values=("", "", ""),
                    tags=('file',)
                )

    def _should_show_dir(self, dirname: str) -> bool:
        """
        Return whether this directory should be displayed, i.e. if
        show_excluded is True or the directory name is not in the
        excluded set.
        """
        if self.show_excluded.get():
            return True
        excluded_dirs = {'venv', '__pycache__', '.venv', 'env', 'node_modules', '.git'}
        return dirname not in excluded_dirs

    ################################################
    # Handling "Show Excluded Dirs" Without Losing Expand States
    ################################################
    def on_toggle_excluded(self) -> None:
        """
        Called when the user toggles "Show Excluded Dirs." We remember expansions,
        then re-build the tree, then restore expansions. This prevents the view
        from collapsing to root.
        """
        expand_states = self._remember_open_states()
        self.refresh_tree()  # re-build
        self._restore_open_states(expand_states)

    def refresh_tree(self) -> None:
        """
        Reload the project_structure.json into the tree, handle top-level
        folders, then apply file-type filtering. We do not forcibly reset
        expansions here, so we can restore them afterwards.
        """
        struct_file = self.structure_output.get()
        path = os.path.join(self.output_dir_entry.get(), struct_file)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    structure: Dict[str, Any] = json.load(f)
                self.tree.delete(*self.tree.get_children())

                top_keys = sorted(structure.keys())
                if len(top_keys) == 1:
                    root_name = top_keys[0]
                    self._build_tree_ascii("", structure[root_name], [], root_name)
                else:
                    for key in top_keys:
                        self._build_tree_ascii("", structure[key], [], key)
            except Exception as e:
                print(f"Error refreshing tree: {str(e)}")

        # Apply file-type filter
        file_type = self.file_types.get()
        if file_type != 'All':
            self._filter_tree_nodes(self.tree.get_children(''), file_type)

    ################################################
    # Copy Tree as ASCII (only visible columns)
    ################################################
    def copy_ascii_tree(self) -> None:
        """
        Re-read the structure from JSON, recursively build ASCII lines
        (subfolders once), and only include columns that are visible in the UI.
        """
        struct_file = os.path.join(self.output_dir_entry.get(), self.structure_output.get())
        if not os.path.isfile(struct_file):
            print("No structure file to copy from.")
            return

        with open(struct_file, 'r', encoding='utf-8') as f:
            data: Dict[str, Any] = json.load(f)

        lines: List[str] = []
        visible_cols = self.tree["displaycolumns"]  # e.g. ('size', 'created')

        # If there's exactly one root, treat that as the name. Otherwise, multiple roots
        top_keys = sorted(data.keys())
        if len(top_keys) == 1:
            root_name = top_keys[0]
            self._ascii_export_folder(folder_name=root_name, data=data[root_name], ancestors=[], lines=lines, visible_cols=visible_cols)
        else:
            # multiple top-level
            for key in top_keys:
                self._ascii_export_folder(folder_name=key, data=data[key], ancestors=[], lines=lines, visible_cols=visible_cols)

        tree_text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(tree_text)
        print("Tree structure (filtered by visible columns) copied to clipboard!")

    def _ascii_export_folder(
        self,
        folder_name: str,
        data: Dict[str, Any],
        ancestors: List[bool],
        lines: List[str],
        visible_cols: Tuple[str, ...]
    ) -> None:
        """
        Insert the subfolder name exactly once, then recursively
        handle subfolders/files. Mirrors the logic of _build_tree_ascii,
        so we do not double-insert subfolder names.

        For folders, if "size" is visible, we append "X files" in parentheses,
        where X is the total file count in the subtree.
        """
        prefix_parts: List[str] = []
        for ancestor_last in ancestors[:-1]:
            prefix_parts.append("    " if ancestor_last else "│   ")
        if ancestors:
            prefix_parts.append("└── " if ancestors[-1] else "├── ")
        ascii_prefix = "".join(prefix_parts)

        # If 'size' is visible, we show "X files" in parentheses for the folder
        folder_line = f"{ascii_prefix}{folder_name}"
        if "size" in visible_cols:
            folder_files_count = self._count_files_in_tree(data)
            folder_line += f" ({folder_files_count} files)"

        lines.append(folder_line)

        subfolders: Dict[str, Any] = data.get("subfolders", {})
        files: List[Union[str, Dict[str, Any]]] = data.get("files", [])

        children: List[Tuple[Any, str, Optional[Dict[str, Any]]]] = []
        for sf_name, sf_data in subfolders.items():
            if self._should_show_dir(sf_name):
                children.append((sf_name, "folder", sf_data))
        for f_item in files:
            if isinstance(f_item, dict) and "name" in f_item:
                children.append((f_item, "fileobj", None))
            else:
                children.append((f_item, "file", None))

        def get_key(ch: Tuple[Any, str, Optional[Dict[str, Any]]]) -> str:
            name, kind, _ = ch
            if kind == "folder":
                return str(name).lower()
            elif kind == "fileobj":
                return str(name["name"]).lower()
            else:
                return str(name).lower()

        children.sort(key=get_key)

        for i, (child, kind, subdata) in enumerate(children):
            is_last_child = (i == len(children) - 1)

            if kind == "folder":
                self._ascii_export_folder(
                    folder_name=str(child),
                    data=subdata,
                    ancestors=ancestors + [is_last_child],
                    lines=lines,
                    visible_cols=visible_cols
                )
            elif kind == "fileobj":
                fname = str(child.get("name", "unknown"))
                size_val = child.get("size", None)
                created_val = child.get("created", None)
                mod_val = child.get("modified", None)
                lines.append(self._ascii_export_file(
                    name=fname,
                    fileinfo=(size_val, created_val, mod_val),
                    ancestors=ancestors + [is_last_child],
                    visible_cols=visible_cols
                ))
            else:
                fname = str(child)
                lines.append(self._ascii_export_file(
                    name=fname,
                    fileinfo=None,
                    ancestors=ancestors + [is_last_child],
                    visible_cols=visible_cols
                ))

    def _ascii_export_file(
        self,
        name: str,
        fileinfo: Optional[Tuple[Any, Any, Any]],
        ancestors: List[bool],
        visible_cols: Tuple[str, ...]
    ) -> str:
        """
        Build a single ASCII line for a file, including parentheses
        for only the columns in visible_cols.

        Args:
            name: The file name.
            fileinfo: (size, created, modified) if available.
            ancestors: Bool list used for indentation.
            visible_cols: Which columns are visible (size, created, modified).
        """
        prefix_parts: List[str] = []
        for ancestor_last in ancestors[:-1]:
            prefix_parts.append("    " if ancestor_last else "│   ")
        if ancestors:
            prefix_parts.append("└── " if ancestors[-1] else "├── ")
        ascii_prefix = "".join(prefix_parts)

        if not fileinfo:
            # plain string or missing metadata
            return f"{ascii_prefix}{name}"

        (size_val, created_val, mod_val) = fileinfo
        extras: List[str] = []
        if "size" in visible_cols and size_val is not None:
            extras.append(f"{size_val} bytes")
        if "created" in visible_cols and created_val:
            extras.append(str(created_val))
        if "modified" in visible_cols and mod_val:
            extras.append(str(mod_val))

        if extras:
            return f"{ascii_prefix}{name} ({', '.join(extras)})"
        else:
            return f"{ascii_prefix}{name}"

    ################################################
    # Expand/Collapse All
    ################################################
    def toggle_tree_view(self, expand: bool = True) -> None:
        """
        Expand or collapse all items in the TreeView.

        Args:
            expand: True to expand all, False to collapse all.
        """
        def _toggle(nodes: Tuple[str, ...]) -> None:
            for nd in nodes:
                self.tree.item(nd, open=expand)
                _toggle(self.tree.get_children(nd))
        _toggle(self.tree.get_children())

    ################################################
    # Filter / Search
    ################################################
    def filter_by_type(self, event: Optional[tk.Event] = None) -> None:
        """
        Triggered when the user changes the file type combobox.
        We remember expansions, re-build, then restore expansions.
        """
        expand_states = self._remember_open_states()
        self.refresh_tree()
        self._restore_open_states(expand_states)

    def _filter_tree_nodes(self, nodes: Tuple[str, ...], file_type: str) -> List[str]:
        """
        Detach any file nodes that do not match the chosen extension.
        Also remove empty folders.
        Returns a list of node IDs that remain visible.
        """
        kept: List[str] = []
        for nd in nodes:
            txt = self.tree.item(nd, 'text')
            is_file = ('file' in self.tree.item(nd, 'tags'))

            # Remove ASCII symbols from the front
            for sym in ["├──", "└──", "│   "]:
                txt = txt.replace(sym, "")
            txt = txt.strip()

            if is_file:
                if not txt.endswith(file_type):
                    self.tree.detach(nd)
                else:
                    kept.append(nd)
            else:
                kids = self._filter_tree_nodes(self.tree.get_children(nd), file_type)
                if not kids and not self.tree.get_children(nd):
                    self.tree.detach(nd)
                else:
                    kept.append(nd)
        return [n for n in kept if self.tree.exists(n)]

    ################################################
    # Searching
    ################################################
    def search_tree(self, event: Optional[tk.Event] = None) -> None:
        """
        Search the tree for items containing the query text.
        Matching items get highlighted and expanded.
        """
        query = self.search_entry.get().lower()
        self._search_tree_nodes(self.tree.get_children(''), query)

    def _search_tree_nodes(self, nodes: Tuple[str, ...], query: str) -> None:
        """
        Recursively search the text of each node. If it matches,
        highlight that node and expand ancestors.
        """
        for nd in nodes:
            txt = self.tree.item(nd, 'text').lower()
            if query in txt:
                self.tree.item(nd, tags=('highlight',))
                self._reveal_node(nd)
            else:
                if 'file' in self.tree.item(nd, 'tags'):
                    self.tree.item(nd, tags=('file',))
                else:
                    self.tree.item(nd, tags=('folder',))
            self._search_tree_nodes(self.tree.get_children(nd), query)

    def _reveal_node(self, node: str) -> None:
        """
        Recursively open all ancestors of this node so it's visible.
        """
        parent = self.tree.parent(node)
        if parent:
            self._reveal_node(parent)
            self.tree.item(parent, open=True)

    ################################################
    # Snapshots
    ################################################
    def save_snapshot(self) -> None:
        """
        Dump the current TreeView structure to a JSON file,
        preserving a minimal subset of info: files vs subfolders.
        """
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            try:
                struct = self._get_tree_structure(self.tree.get_children(''))
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(struct, f, indent=2)
                messagebox.showinfo("Success", f"Snapshot saved to {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save snapshot: {str(e)}")

    def load_snapshot(self) -> None:
        """
        Load a previously saved TreeView snapshot from JSON
        and repopulate the tree with ASCII indentation.
        """
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            expand_states = self._remember_open_states()
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    structure: Dict[str, Any] = json.load(f)
                self.tree.delete(*self.tree.get_children())

                top_keys = sorted(structure.keys())
                if len(top_keys) == 1:
                    root_name = top_keys[0]
                    self._build_tree_ascii("", structure[root_name], [], root_name)
                else:
                    for key in top_keys:
                        self._build_tree_ascii("", structure[key], [], key)

                messagebox.showinfo("Success", "Snapshot loaded successfully")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load snapshot: {str(e)}")
                return

            self._restore_open_states(expand_states)

    def _get_tree_structure(self, nodes: Tuple[str, ...]) -> Dict[str, Any]:
        """
        Reconstruct a minimal structure from the current TreeView.

        For each folder, gather its files and subfolders. For each file,
        store it in the "files" list.

        Args:
            nodes: A tuple of node IDs at this level in the tree.

        Returns:
            A dict where each key is a folder name mapped to its sub-structure.
        """
        structure: Dict[str, Any] = {}
        for nd in nodes:
            txt = self.tree.item(nd, 'text')
            # remove the ASCII prefix
            for sym in ["├──", "└──", "│   "]:
                txt = txt.replace(sym, "")
            folder_or_file_name = txt.strip()

            is_file = ('file' in self.tree.item(nd, 'tags'))
            kids = self.tree.get_children(nd)

            if is_file:
                # It's a file, so store a minimal "files": [] structure
                structure[folder_or_file_name] = {
                    "files": [],
                    "subfolders": {}
                }
            else:
                # It's a folder, gather child structure
                child_struct = self._get_tree_structure(kids)
                files_list: List[str] = []
                subfolders_dict: Dict[str, Any] = {}
                for k, v in child_struct.items():
                    # If the child has no subfolders, that means it's a file
                    if v["subfolders"]:
                        subfolders_dict[k] = v
                    elif not v["files"]:
                        files_list.append(k)
                    else:
                        files_list.append(k)

                structure[folder_or_file_name] = {
                    "files": files_list,
                    "subfolders": subfolders_dict
                }
        return structure

    ################################################
    # About
    ################################################
    def show_about(self) -> None:
        """
        Shows an 'About' dialog with author/license info.
        """
        messagebox.showinfo(
            "About Project Tools Runner",
            (
                "Developed by Siddharth Venkumahnati.\n"
                "Licensed under the MIT License.\n\n"
                "GitHub: https://github.com/sidbetatester/AI-Dev-Kit"
            )
        )

    ################################################
    # Utility: Counting Files in a Folder's Subtree
    ################################################
    def _count_files_in_tree(self, data: Dict[str, Any]) -> int:
        """
        Recursively count how many files are in the given folder's subtree.

        Args:
            data: A dict with "files" (list of strings or dicts)
                  and "subfolders" (dict of folder_name->subtree).
        Returns:
            The total number of files in this folder and its subfolders.
        """
        total = len(data.get("files", []))
        for sf_name, sf_data in data.get("subfolders", {}).items():
            total += self._count_files_in_tree(sf_data)
        return total

    ################################################
    # Utility: Remembering / Restoring Expansion States
    ################################################
    def _remember_open_states(self) -> Dict[str, bool]:
        """
        Recursively record which nodes are open in the current tree,
        using a path-based dictionary so we can restore expansions
        after rebuilding.

        Returns:
            A dict of { full_node_path: bool }, where True means
            the node is open (expanded), False means closed.
        """
        states: Dict[str, bool] = {}
        def _walk(node: str, path: str) -> None:
            is_open = self.tree.item(node, "open")
            states[path] = is_open
            for child in self.tree.get_children(node):
                child_text = self.tree.item(child, "text")
                subpath = path + "/" + child_text
                _walk(child, subpath)
        # Walk each child of root
        for root_child in self.tree.get_children(''):
            root_text = self.tree.item(root_child, "text")
            _walk(root_child, root_text)
        return states

    def _restore_open_states(self, states: Dict[str, bool]) -> None:
        """
        Given a dict of expansions { full_node_path: bool }, traverse
        the newly built tree, matching each node's path. If found in states,
        set the open/closed accordingly.

        Args:
            states: dict of { full_node_path: bool }
        """
        def _walk(node: str, path: str) -> None:
            if path in states:
                self.tree.item(node, open=states[path])
            for child in self.tree.get_children(node):
                child_text = self.tree.item(child, "text")
                subpath = path + "/" + child_text
                _walk(child, subpath)
        for root_child in self.tree.get_children(''):
            root_text = self.tree.item(root_child, "text")
            _walk(root_child, root_text)


################################################
# Main Entrypoint
################################################
if __name__ == "__main__":
    app = ToolRunnerUI()
    app.mainloop()
