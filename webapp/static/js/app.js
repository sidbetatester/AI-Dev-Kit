(function () {
  "use strict";

  const form = document.getElementById("analyze-form");
  const runBtn = document.getElementById("run-btn");
  const statusEl = document.getElementById("status");
  const summaryEl = document.getElementById("summary");
  const treeEl = document.getElementById("tree");
  const filesOutput = document.getElementById("files-output");
  const filesStats = document.getElementById("files-stats");
  const logsOutput = document.getElementById("logs-output");
  const treeSearch = document.getElementById("tree-search");
  const toast = document.getElementById("toast");

  let currentStructure = null;
  let lastOutputs = { text: null, json: null, log: null };
  let pyodidePromise = null;
  let gitLibsPromise = null;
  let selectedDirHandle = null;
  let selectedFiles = null;

  // ---- Tabs -------------------------------------------------------------
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
    });
  });

  // ---- Helpers ----------------------------------------------------------
  function humanSize(bytes) {
    if (bytes === null || bytes === undefined) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i++;
    }
    return (i === 0 ? n : n.toFixed(1)) + " " + units[i];
  }

  function setStatus(message) {
    statusEl.textContent = message || "";
  }

  function showToast(message, isError) {
    toast.textContent = message;
    toast.classList.toggle("error", !!isError);
    toast.classList.remove("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  function triggerDownload(filename, content) {
    if (content == null) return;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function setDownloadEnabled(id, enabled) {
    document.getElementById(id).classList.toggle("disabled", !enabled);
  }

  // ---- Pyodide bootstrap ------------------------------------------------
  function ensurePyodide() {
    if (pyodidePromise) return pyodidePromise;
    pyodidePromise = (async () => {
      setStatus("Loading Python runtime (one-time, ~10s)...");
      const pyodide = await loadPyodide();
      const modules = ["file_loader_tool.py", "project_structure_tool.py"];
      for (const name of modules) {
        const res = await fetch("/core/" + name);
        if (!res.ok) throw new Error("Could not load core module: " + name);
        pyodide.FS.writeFile("/home/pyodide/" + name, await res.text());
      }
      const runnerRes = await fetch("/static/py/runner.py");
      pyodide.runPython(await runnerRes.text());
      setStatus("");
      return pyodide;
    })();
    return pyodidePromise;
  }

  // ---- Public Git repo clone (client-side, in-browser) ------------------
  // Browsers can't speak the raw git protocol, so the clone runs over HTTPS
  // via isomorphic-git relayed through a CORS proxy. Public repos only, no
  // token. The user's own machine files are never uploaded. The clone lives in
  // an in-memory filesystem (memfs) — nothing is persisted to disk/IndexedDB.
  function ensureGitLibs() {
    if (gitLibsPromise) return gitLibsPromise;
    gitLibsPromise = (async () => {
      setStatus("Loading git client (one-time)...");
      try {
        const [gitMod, httpMod, memfsMod] = await Promise.all([
          import("https://esm.sh/isomorphic-git@1.27.1"),
          import("https://esm.sh/isomorphic-git@1.27.1/http/web"),
          import("https://esm.sh/memfs@4"),
        ]);
        setStatus("");
        return {
          git: gitMod.default || gitMod,
          http: httpMod.default || httpMod,
          Volume: memfsMod.Volume,
          createFsFromVolume: memfsMod.createFsFromVolume,
        };
      } catch (e) {
        // Don't poison future attempts: a transient import failure should be
        // retryable without a full page reload.
        gitLibsPromise = null;
        throw e;
      }
    })();
    return gitLibsPromise;
  }

  function repoNameFromUrl(url) {
    let pathname = url.trim();
    try {
      pathname = new URL(url.trim()).pathname;
    } catch (e) {
      /* not a parseable absolute URL — fall back to raw string parsing */
    }
    const u = pathname.replace(/\/+$/, "").replace(/\.git$/i, "");
    const segs = u.split("/").filter(Boolean);
    const last = segs.length ? segs[segs.length - 1] : "";
    // Sanitize to a safe directory slug (strip query/fragment leftovers, etc.).
    const slug = last.replace(/[^A-Za-z0-9._-]/g, "_");
    return slug || "repo";
  }

  async function cloneRepoToFs(pyodide, url, excludeSet, corsProxy) {
    const { git, http, Volume, createFsFromVolume } = await ensureGitLibs();
    // Fresh in-memory volume per clone; it is garbage-collected once references
    // drop after we copy the files out — no cleanup, no persistence.
    const vol = new Volume();
    const mfs = createFsFromVolume(vol);
    const pfs = mfs.promises;
    const dir = "/repo";
    await pfs.mkdir(dir, { recursive: true });

    setStatus("Cloning repository in your browser...");
    await git.clone({
      fs: mfs,
      http,
      dir,
      url,
      corsProxy: corsProxy || undefined,
      singleBranch: true,
      depth: 1,
      onProgress: (e) => {
        if (!e || !e.phase) return;
        const pct = e.total ? " " + Math.round((e.loaded / e.total) * 100) + "%" : "";
        setStatus("Cloning: " + e.phase + pct);
      },
    });

    // Reset the working tree, then copy the clone into Pyodide's MEMFS so the
    // exact same downstream "run tools" path is reused.
    pyodide.runPython(
      "import shutil, os; shutil.rmtree('/work', ignore_errors=True); os.makedirs('/work', exist_ok=True)"
    );
    const FS = pyodide.FS;
    const rootName = repoNameFromUrl(url);
    const rootPath = "/work/" + rootName;
    FS.mkdirTree(rootPath);

    let count = 0;
    async function copyDir(srcDir, destDir) {
      const entries = await pfs.readdir(srcDir);
      for (const name of entries) {
        const srcPath = srcDir === "/" ? "/" + name : srcDir + "/" + name;
        const destPath = destDir + "/" + name;
        const st = await pfs.stat(srcPath);
        if (st.isDirectory()) {
          // Create every directory (including excluded ones) as a placeholder
          // so the Python tools see/count it exactly like the folder picker.
          FS.mkdirTree(destPath);
          if (!excludeSet.has(name)) {
            await copyDir(srcPath, destPath);
          }
        } else {
          const data = await pfs.readFile(srcPath);
          FS.writeFile(destPath, data);
          try {
            FS.utime(destPath, st.mtimeMs, st.mtimeMs);
          } catch (e) {
            /* best effort */
          }
          count++;
          if (count % 200 === 0) {
            setStatus("Copying files... " + count);
            await new Promise((r) => setTimeout(r, 0));
          }
        }
      }
    }
    await copyDir(dir, rootPath);

    return { rootName, written: count };
  }

  // ---- Build the in-browser filesystem from the picked folder ----------
  function buildExcludeSet(useDefaults, excludeText) {
    const set = new Set(
      excludeText.split(",").map((s) => s.trim()).filter(Boolean)
    );
    if (useDefaults) {
      (window.DEFAULT_EXCLUDES || []).forEach((d) => set.add(d));
    }
    return set;
  }

  async function populateFsFromHandle(pyodide, dirHandle, excludeSet) {
    pyodide.runPython(
      "import shutil, os; shutil.rmtree('/work', ignore_errors=True); os.makedirs('/work', exist_ok=True)"
    );
    const FS = pyodide.FS;
    const rootName = dirHandle.name || "project";
    const rootPath = "/work/" + rootName;
    FS.mkdirTree(rootPath);

    let count = 0;
    async function recurse(handle, path) {
      for await (const entry of handle.values()) {
        const childPath = path + "/" + entry.name;
        if (entry.kind === "directory") {
          // Create every directory (including empty ones) so the structure
          // matches the desktop tool exactly. Excluded dirs are created as
          // empty placeholders and not descended into.
          FS.mkdirTree(childPath);
          if (!excludeSet.has(entry.name)) {
            await recurse(entry, childPath);
          }
        } else {
          const file = await entry.getFile();
          FS.writeFile(childPath, new Uint8Array(await file.arrayBuffer()));
          try {
            FS.utime(childPath, file.lastModified, file.lastModified);
          } catch (e) {
            /* best effort */
          }
          count++;
          if (count % 200 === 0) {
            setStatus("Reading files locally... " + count);
            await new Promise((r) => setTimeout(r, 0));
          }
        }
      }
    }
    await recurse(dirHandle, rootPath);
    return { rootName, written: count };
  }

  async function populateFs(pyodide, files, excludeSet) {
    // Reset the working tree.
    pyodide.runPython(
      "import shutil, os; shutil.rmtree('/work', ignore_errors=True); os.makedirs('/work', exist_ok=True)"
    );
    const FS = pyodide.FS;
    const rootName = files[0].webkitRelativePath.split("/")[0] || "project";

    let written = 0;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const parts = file.webkitRelativePath.split("/");
      const filename = parts[parts.length - 1];
      const dirSegs = parts.slice(1, -1); // segments below the root folder

      // Determine if this file lives inside an excluded directory.
      let exclIdx = -1;
      for (let j = 0; j < dirSegs.length; j++) {
        if (excludeSet.has(dirSegs[j])) {
          exclIdx = j;
          break;
        }
      }

      if (exclIdx >= 0) {
        // Create the outermost excluded dir (empty) so the Python tools still
        // see and count it exactly as the desktop app would, without loading
        // its contents into memory.
        const exclPath =
          "/work/" + parts[0] + "/" + dirSegs.slice(0, exclIdx + 1).join("/");
        FS.mkdirTree(exclPath);
        continue;
      }

      const dirPath = "/work/" + parts.slice(0, -1).join("/");
      FS.mkdirTree(dirPath);
      const fsPath = dirPath + "/" + filename;
      const buf = new Uint8Array(await file.arrayBuffer());
      FS.writeFile(fsPath, buf);
      // Preserve the real last-modified time (Emscripten utime takes ms).
      try {
        FS.utime(fsPath, file.lastModified, file.lastModified);
      } catch (e) {
        /* best effort */
      }

      written++;
      if (i % 200 === 0) {
        setStatus("Reading files locally... " + (i + 1) + "/" + files.length);
        await new Promise((r) => setTimeout(r, 0));
      }
    }
    return { rootName, written };
  }

  // ---- Tree rendering ---------------------------------------------------
  function countDescendants(node) {
    let files = node.files ? node.files.length : 0;
    let folders = 0;
    const subs = node.subfolders || {};
    for (const key of Object.keys(subs)) {
      folders += 1;
      const c = countDescendants(subs[key]);
      files += c.files;
      folders += c.folders;
    }
    return { files, folders };
  }

  function makeRow(name, isDir, meta, depth) {
    const row = document.createElement("div");
    row.className = "node-row";
    row.style.paddingLeft = depth * 16 + "px";

    const twisty = document.createElement("span");
    twisty.className = "twisty" + (isDir ? "" : " leaf");
    twisty.textContent = isDir ? "▾" : "•";
    row.appendChild(twisty);

    const nameEl = document.createElement("span");
    nameEl.className = "node-name " + (isDir ? "dir" : "file");
    nameEl.textContent = name;
    nameEl.dataset.name = name.toLowerCase();
    row.appendChild(nameEl);

    const sizeMeta = document.createElement("span");
    sizeMeta.className = "meta meta-size";
    sizeMeta.textContent = meta.size || "";
    row.appendChild(sizeMeta);

    const modMeta = document.createElement("span");
    modMeta.className = "meta meta-modified";
    modMeta.textContent = meta.modified || "";
    row.appendChild(modMeta);

    return { row, twisty };
  }

  function renderNode(name, node, depth) {
    const container = document.createElement("div");
    container.className = "node";

    const counts = countDescendants(node);
    const { row, twisty } = makeRow(
      name,
      true,
      { size: counts.files + " files", modified: "" },
      depth
    );
    container.appendChild(row);

    const children = document.createElement("div");
    children.className = "children";

    const subs = node.subfolders || {};
    Object.keys(subs)
      .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))
      .forEach((key) => {
        children.appendChild(renderNode(key, subs[key], depth + 1));
      });

    (node.files || [])
      .slice()
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
      .forEach((file) => {
        const { row: fileRow } = makeRow(
          file.name,
          false,
          { size: humanSize(file.size), modified: file.modified || "" },
          depth + 1
        );
        children.appendChild(fileRow);
      });

    container.appendChild(children);

    twisty.addEventListener("click", () => {
      const collapsed = children.classList.toggle("collapsed");
      twisty.textContent = collapsed ? "▸" : "▾";
    });

    return container;
  }

  function renderTree() {
    treeEl.innerHTML = "";
    if (!currentStructure) {
      treeEl.innerHTML = '<p class="empty">Pick a folder and run the tools to see your project structure here.</p>';
      return;
    }
    const rootName = Object.keys(currentStructure)[0];
    treeEl.appendChild(renderNode(rootName, currentStructure[rootName], 0));
    applyColumnVisibility();
  }

  function applyColumnVisibility() {
    const showSize = document.getElementById("show-size").checked;
    const showMod = document.getElementById("show-modified").checked;
    treeEl.querySelectorAll(".meta-size").forEach((e) => (e.style.display = showSize ? "" : "none"));
    treeEl.querySelectorAll(".meta-modified").forEach((e) => (e.style.display = showMod ? "" : "none"));
  }

  // ---- ASCII export -----------------------------------------------------
  function buildAscii(name, node, prefix, isLast, lines) {
    const connector = prefix === "" ? "" : isLast ? "└── " : "├── ";
    lines.push(prefix + connector + name + "/");
    const childPrefix = prefix === "" ? "" : prefix + (isLast ? "    " : "│   ");

    const subNames = Object.keys(node.subfolders || {}).sort((a, b) =>
      a.toLowerCase().localeCompare(b.toLowerCase())
    );
    const files = (node.files || [])
      .slice()
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

    const total = subNames.length + files.length;
    let idx = 0;
    subNames.forEach((key) => {
      idx++;
      buildAscii(key, node.subfolders[key], childPrefix, idx === total, lines);
    });
    files.forEach((file) => {
      idx++;
      const last = idx === total;
      lines.push(childPrefix + (last ? "└── " : "├── ") + file.name);
    });
  }

  // ---- Search filter ----------------------------------------------------
  function filterTree(query) {
    const q = query.trim().toLowerCase();
    const rows = treeEl.querySelectorAll(".node-row");
    if (!q) {
      rows.forEach((r) => {
        r.classList.remove("hidden");
        const nameEl = r.querySelector(".node-name");
        nameEl.innerHTML = nameEl.textContent;
      });
      return;
    }
    rows.forEach((r) => {
      const nameEl = r.querySelector(".node-name");
      const name = nameEl.dataset.name || "";
      if (name.includes(q)) {
        r.classList.remove("hidden");
        const original = nameEl.textContent;
        const i = name.indexOf(q);
        nameEl.innerHTML =
          original.slice(0, i) +
          "<mark>" +
          original.slice(i, i + q.length) +
          "</mark>" +
          original.slice(i + q.length);
      } else {
        r.classList.add("hidden");
      }
    });
  }

  // ---- Events -----------------------------------------------------------
  treeSearch.addEventListener("input", (e) => filterTree(e.target.value));
  document.getElementById("show-size").addEventListener("change", applyColumnVisibility);
  document.getElementById("show-modified").addEventListener("change", applyColumnVisibility);

  document.getElementById("expand-all").addEventListener("click", () => {
    treeEl.querySelectorAll(".children").forEach((c) => c.classList.remove("collapsed"));
    treeEl.querySelectorAll(".twisty:not(.leaf)").forEach((t) => (t.textContent = "▾"));
  });
  document.getElementById("collapse-all").addEventListener("click", () => {
    treeEl.querySelectorAll(".node .children").forEach((c, idx) => {
      if (idx > 0) c.classList.add("collapsed");
    });
    treeEl.querySelectorAll(".node .twisty:not(.leaf)").forEach((t, idx) => {
      if (idx > 0) t.textContent = "▸";
    });
  });
  document.getElementById("copy-ascii").addEventListener("click", () => {
    if (!currentStructure) {
      showToast("Nothing to copy yet.", true);
      return;
    }
    const rootName = Object.keys(currentStructure)[0];
    const lines = [];
    buildAscii(rootName, currentStructure[rootName], "", true, lines);
    const text = lines.join("\n");
    navigator.clipboard.writeText(text).then(
      () => showToast("ASCII tree copied to clipboard."),
      () => showToast("Copy failed.", true)
    );
  });

  document.getElementById("download-text").addEventListener("click", () =>
    triggerDownload("loaded_files_output.txt", lastOutputs.text)
  );
  document.getElementById("download-json").addEventListener("click", () =>
    triggerDownload("project_structure.json", lastOutputs.json)
  );
  document.getElementById("download-log").addEventListener("click", () =>
    triggerDownload("file_loader_log.txt", lastOutputs.log)
  );

  const folderInput = document.getElementById("project-folder");
  const folderNameEl = document.getElementById("folder-name");
  const localField = document.getElementById("local-field");
  const gitField = document.getElementById("git-field");
  const gitUrlEl = document.getElementById("git-url");
  const corsProxyEl = document.getElementById("cors-proxy");

  function getInputMode() {
    const checked = document.querySelector('input[name="input-mode"]:checked');
    return checked ? checked.value : "local";
  }

  function applyInputMode() {
    const mode = getInputMode();
    localField.classList.toggle("hidden", mode !== "local");
    gitField.classList.toggle("hidden", mode !== "git");
  }

  document.querySelectorAll('input[name="input-mode"]').forEach((radio) => {
    radio.addEventListener("change", applyInputMode);
  });
  applyInputMode();

  document.getElementById("pick-folder").addEventListener("click", async () => {
    if (window.showDirectoryPicker) {
      try {
        selectedDirHandle = await window.showDirectoryPicker();
        selectedFiles = null;
        folderNameEl.textContent = selectedDirHandle.name;
      } catch (e) {
        /* user cancelled */
      }
    } else {
      folderInput.click();
    }
  });

  folderInput.addEventListener("change", () => {
    if (folderInput.files && folderInput.files.length) {
      selectedFiles = folderInput.files;
      selectedDirHandle = null;
      folderNameEl.textContent =
        folderInput.files[0].webkitRelativePath.split("/")[0] || "Selected folder";
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const inputMode = getInputMode();
    const gitUrl = gitUrlEl.value.trim();

    if (inputMode === "git") {
      if (!gitUrl) {
        showToast("Enter a public repository URL first.", true);
        return;
      }
    } else if (!selectedDirHandle && (!selectedFiles || !selectedFiles.length)) {
      showToast("Choose a project folder first.", true);
      return;
    }
    const runLoader = document.getElementById("run-loader").checked;
    const runStructure = document.getElementById("run-structure").checked;
    if (!runLoader && !runStructure) {
      showToast("Select at least one tool to run.", true);
      return;
    }

    const useDefaults = document.getElementById("use-defaults").checked;
    const excludeText = document.getElementById("exclude-dirs").value;
    const excludeSet = buildExcludeSet(useDefaults, excludeText);

    runBtn.disabled = true;
    runBtn.textContent = "Running...";

    try {
      const pyodide = await ensurePyodide();
      let rootName;
      if (inputMode === "git") {
        ({ rootName } = await cloneRepoToFs(
          pyodide,
          gitUrl,
          excludeSet,
          corsProxyEl.value.trim()
        ));
      } else {
        ({ rootName } = selectedDirHandle
          ? await populateFsFromHandle(pyodide, selectedDirHandle, excludeSet)
          : await populateFs(pyodide, selectedFiles, excludeSet));
      }

      setStatus("Running tools in your browser...");
      await new Promise((r) => setTimeout(r, 0));

      const runFn = pyodide.globals.get("run_tools");
      // Signature: run_tools(root, run_loader, run_structure, exclude_csv, use_defaults)
      const resultJson = runFn(
        "/work/" + rootName,
        runLoader ? true : false,
        runStructure ? true : false,
        excludeText,
        useDefaults
      );
      runFn.destroy();

      const data = JSON.parse(resultJson);
      renderResults(data);
      setStatus("");
      showToast("Analysis complete — processed locally, nothing uploaded.");
    } catch (err) {
      console.error(err);
      setStatus("");
      showToast("Failed: " + (err && err.message ? err.message : err), true);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Run Tools";
    }
  });

  function renderResults(data) {
    // Structure
    if (data.structure) {
      currentStructure = data.structure;
      lastOutputs.json = data.structure_json || null;
      renderTree();
      setDownloadEnabled("download-json", true);
    } else {
      currentStructure = null;
      lastOutputs.json = null;
      renderTree();
      setDownloadEnabled("download-json", false);
    }

    // Loader
    if (data.loader) {
      const l = data.loader;
      lastOutputs.text = data.loader_text || null;
      lastOutputs.log = data.loader_log || null;
      filesOutput.textContent =
        l.preview + (l.truncated ? "\n\n... (truncated — download the full file) ..." : "");
      filesStats.textContent =
        l.processed +
        " files processed · " +
        l.skipped +
        " skipped · " +
        l.total_chars.toLocaleString() +
        " characters";
      setDownloadEnabled("download-text", true);
      setDownloadEnabled("download-log", true);
    } else {
      lastOutputs.text = null;
      lastOutputs.log = null;
      filesOutput.innerHTML = '<span class="empty">File loader was not run.</span>';
      filesStats.textContent = "";
      setDownloadEnabled("download-text", false);
      setDownloadEnabled("download-log", false);
    }

    // Logs
    logsOutput.textContent = (data.logs || []).join("\n") || "No log output.";

    // Summary
    renderSummary(data);
  }

  function renderSummary(data) {
    const cards = [];
    if (data.structure) {
      const root = data.structure[Object.keys(data.structure)[0]];
      const c = countDescendants(root);
      cards.push(["Folders", c.folders]);
      cards.push(["Files", c.files]);
    }
    if (data.loader) {
      cards.push(["Processed", data.loader.processed]);
      cards.push(["Skipped", data.loader.skipped]);
    }
    if (!cards.length) {
      summaryEl.classList.add("hidden");
      return;
    }
    summaryEl.innerHTML = cards
      .map(
        ([label, num]) =>
          '<div class="stat"><span class="num">' + num + '</span><span class="label">' + label + "</span></div>"
      )
      .join("");
    summaryEl.classList.remove("hidden");
  }
})();
