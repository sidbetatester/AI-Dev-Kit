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
  let lastExcludeSet = new Set();
  let lastData = null;
  let cancelRequested = false;
  let pendingTypeFilter = null;

  const cancelBtn = document.getElementById("cancel-btn");
  const progressEl = document.getElementById("progress");
  const typeFilter = document.getElementById("type-filter");
  const showExcludedEl = document.getElementById("show-excluded");
  const SETTINGS_KEY = "ptr-settings-v1";
  const CANCELLED = "__cancelled__";

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
    showToast._t = setTimeout(() => toast.classList.add("hidden"), isError ? 7000 : 3200);
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

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function fileExt(name) {
    const i = name.lastIndexOf(".");
    if (i <= 0) return ""; // no extension, or a dotfile like ".gitignore"
    return name.slice(i).toLowerCase();
  }

  function checkCancelled() {
    if (cancelRequested) throw new Error(CANCELLED);
  }

  function showProgress() {
    progressEl.classList.remove("hidden");
    setIndeterminate();
  }
  function hideProgress() {
    progressEl.classList.add("hidden");
    progressEl.removeAttribute("value");
  }
  function setProgress(value, max) {
    progressEl.max = max || 100;
    progressEl.value = value;
  }
  function setIndeterminate() {
    progressEl.removeAttribute("value");
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
        // memfs's ESM build only exposes a default export; Volume and
        // createFsFromVolume live on it (no named exports), so fall back to
        // the default object when the named exports are absent.
        const memfs = memfsMod.default || memfsMod;
        return {
          git: gitMod.default || gitMod,
          http: httpMod.default || httpMod,
          Volume: memfsMod.Volume || memfs.Volume,
          createFsFromVolume: memfsMod.createFsFromVolume || memfs.createFsFromVolume,
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
        checkCancelled();
        if (!e || !e.phase) return;
        if (e.total) setProgress(e.loaded, e.total);
        else setIndeterminate();
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
        checkCancelled();
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

  // ---- GitHub fast path (no CORS proxy needed) -------------------------
  // GitHub's own git/codeload endpoints do not send permissive CORS headers,
  // which is why isomorphic-git needs a relay. The jsDelivr CDN, however,
  // mirrors public GitHub repos and serves both its file-list API and file
  // contents with `Access-Control-Allow-Origin: *`, so we can fetch an entire
  // public GitHub repo directly from the browser — no server, no proxy.
  function parseGithubUrl(url) {
    let host;
    let segs;
    const raw = url.trim();
    try {
      const parsed = new URL(raw);
      host = parsed.hostname.toLowerCase();
      segs = parsed.pathname.split("/").filter(Boolean);
    } catch (e) {
      const m = raw.match(/^git@github\.com:(.+)$/i);
      if (!m) return null;
      host = "github.com";
      segs = m[1].split("/").filter(Boolean);
    }
    if (host !== "github.com" && host !== "www.github.com") return null;
    if (segs.length < 2) return null;
    const owner = segs[0];
    const repo = segs[1].replace(/\.git$/i, "");
    if (!owner || !repo) return null;
    // Support .../tree/<ref> URLs so a specific branch/tag can be requested.
    let ref = null;
    if (segs.length >= 4 && segs[2] === "tree") ref = decodeURIComponent(segs[3]);
    return { owner, repo, ref };
  }

  async function resolveGithubRef(owner, repo, ref) {
    if (ref) return ref;
    // GitHub's REST API is CORS-enabled; one request resolves the default
    // branch. If it fails (e.g. rate-limited), the caller falls back to
    // trying the common default branch names against jsDelivr.
    try {
      const res = await fetch(
        "https://api.github.com/repos/" +
          encodeURIComponent(owner) +
          "/" +
          encodeURIComponent(repo),
        { headers: { Accept: "application/vnd.github+json" } }
      );
      if (res.ok) {
        const data = await res.json();
        if (data && data.default_branch) return data.default_branch;
      }
    } catch (e) {
      /* fall through to common-default-branch probing */
    }
    return null;
  }

  async function fetchGithubViaJsdelivr(pyodide, owner, repo, ref, excludeSet) {
    setStatus("Resolving repository...");
    setIndeterminate();
    const resolved = await resolveGithubRef(owner, repo, ref);
    const candidates = resolved ? [resolved] : ["main", "master"];

    let files = null;
    let usedRef = null;
    for (const cand of candidates) {
      checkCancelled();
      const api =
        "https://data.jsdelivr.com/v1/packages/gh/" +
        encodeURIComponent(owner) +
        "/" +
        encodeURIComponent(repo) +
        "@" +
        encodeURIComponent(cand) +
        "?structure=flat";
      const res = await fetch(api);
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.files)) {
          files = data.files;
          usedRef = cand;
          break;
        }
      }
    }
    if (files === null) throw new Error("jsdelivr-list-failed");

    pyodide.runPython(
      "import shutil, os; shutil.rmtree('/work', ignore_errors=True); os.makedirs('/work', exist_ok=True)"
    );
    const FS = pyodide.FS;
    const rootName = repoNameFromUrl(repo);
    const rootPath = "/work/" + rootName;
    FS.mkdirTree(rootPath);

    // Partition into files to download vs. excluded-dir placeholders, mirroring
    // the local folder flow: excluded dirs are recreated empty (so the Python
    // tools still see/count them) but their contents are never fetched.
    const toFetch = [];
    for (const f of files) {
      const rel = String((f && f.name) || "").replace(/^\/+/, "");
      if (!rel) continue;
      const segs = rel.split("/");
      const dirSegs = segs.slice(0, -1);
      let exclIdx = -1;
      for (let j = 0; j < dirSegs.length; j++) {
        if (excludeSet.has(dirSegs[j])) {
          exclIdx = j;
          break;
        }
      }
      if (exclIdx >= 0) {
        FS.mkdirTree(rootPath + "/" + dirSegs.slice(0, exclIdx + 1).join("/"));
        continue;
      }
      toFetch.push({ rel, segs });
    }

    const total = toFetch.length;
    let done = 0;
    setStatus("Downloading " + total + " files...");
    setProgress(0, total);

    const cdnBase =
      "https://cdn.jsdelivr.net/gh/" + owner + "/" + repo + "@" + usedRef;
    let next = 0;
    async function worker() {
      while (next < toFetch.length) {
        const { rel, segs } = toFetch[next++];
        checkCancelled();
        const dirPath =
          segs.length > 1
            ? rootPath + "/" + segs.slice(0, -1).join("/")
            : rootPath;
        FS.mkdirTree(dirPath);
        const cdnUrl =
          cdnBase + "/" + rel.split("/").map(encodeURIComponent).join("/");
        const res = await fetch(cdnUrl);
        if (!res.ok) {
          throw new Error(
            "Couldn't download " + rel + " (HTTP " + res.status + ")"
          );
        }
        FS.writeFile(rootPath + "/" + rel, new Uint8Array(await res.arrayBuffer()));
        done++;
        if (done % 25 === 0 || done === total) {
          setProgress(done, total);
          setStatus("Downloading files... " + done + "/" + total);
          await new Promise((r) => setTimeout(r, 0));
        }
      }
    }
    const pool = [];
    for (let w = 0; w < Math.min(6, toFetch.length); w++) pool.push(worker());
    await Promise.all(pool);

    return { rootName, written: done };
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
        checkCancelled();
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
      checkCancelled();
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
        setProgress(i + 1, files.length);
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
      // Excluded placeholders are display-only — they aren't part of the real
      // counts (keeps totals identical to the pruned structure / desktop).
      if (subs[key] && subs[key].excluded) continue;
      folders += 1;
      const c = countDescendants(subs[key]);
      files += c.files;
      folders += c.folders;
    }
    return { files, folders };
  }

  function makeRow(name, isDir, meta, ancestors, opts) {
    opts = opts || {};
    const row = document.createElement("div");
    row.className = "node-row" + (opts.excluded ? " excluded-dir" : "");
    if (!isDir) row.dataset.ext = fileExt(name);

    const prefix = document.createElement("span");
    prefix.className = "tree-prefix";
    prefix.setAttribute("aria-hidden", "true");
    prefix.textContent = asciiPrefix(ancestors);
    row.appendChild(prefix);

    const twisty = document.createElement("span");
    twisty.className = "twisty" + (isDir ? "" : " leaf");
    twisty.textContent = isDir ? "▾" : "•";
    row.appendChild(twisty);

    const nameEl = document.createElement("span");
    nameEl.className = "node-name " + (isDir ? "dir" : "file");
    nameEl.dataset.name = name.toLowerCase();

    const label = document.createElement("span");
    label.className = "node-label";
    label.textContent = isDir ? name + "/" : name;
    label.dataset.text = name;
    nameEl.appendChild(label);

    if (opts.excluded) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "excluded";
      nameEl.appendChild(badge);
    }
    row.appendChild(nameEl);

    const sizeMeta = document.createElement("span");
    sizeMeta.className = "meta meta-size";
    sizeMeta.textContent = meta.size || "";
    row.appendChild(sizeMeta);

    const createdMeta = document.createElement("span");
    createdMeta.className = "meta meta-created";
    createdMeta.textContent = meta.created || "";
    row.appendChild(createdMeta);

    const modMeta = document.createElement("span");
    modMeta.className = "meta meta-modified";
    modMeta.textContent = meta.modified || "";
    row.appendChild(modMeta);

    return { row, twisty };
  }

  function renderNode(name, node, ancestors) {
    const container = document.createElement("div");
    container.className = "node";

    const isExcluded = !!(node && node.excluded);
    const counts = countDescendants(node);
    const { row, twisty } = makeRow(
      name,
      true,
      { size: counts.files + " files", created: "", modified: "" },
      ancestors,
      { excluded: isExcluded }
    );
    container.appendChild(row);

    const children = document.createElement("div");
    children.className = "children";

    const subs = node.subfolders || {};
    const subNames = Object.keys(subs).sort((a, b) =>
      a.toLowerCase().localeCompare(b.toLowerCase())
    );
    const files = (node.files || [])
      .slice()
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    const totalChildren = subNames.length + files.length;

    subNames.forEach((key, index) => {
      const isLast = index === totalChildren - 1;
      children.appendChild(renderNode(key, subs[key], ancestors.concat(isLast)));
    });

    files.forEach((file, index) => {
      const isLast = subNames.length + index === totalChildren - 1;
      const { row: fileRow } = makeRow(
        file.name,
        false,
        { size: humanSize(file.size), created: file.created || "", modified: file.modified || "" },
        ancestors.concat(isLast)
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
    const treeHead = document.getElementById("tree-head");
    // Clear previous content but keep the sticky column-header row in place.
    Array.from(treeEl.children).forEach((c) => {
      if (c !== treeHead) c.remove();
    });
    if (!currentStructure) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent =
        "Pick a folder and run the tools to see your project structure here.";
      treeEl.appendChild(empty);
      if (treeHead) treeHead.hidden = true;
      return;
    }
    if (treeHead) treeHead.hidden = false;
    const rootName = Object.keys(currentStructure)[0];
    treeEl.appendChild(renderNode(rootName, currentStructure[rootName], []));
    applyColumnVisibility();
    populateTypeFilter();
    applyFilters();
  }

  function collectExts(node, set) {
    (node.files || []).forEach((f) => set.add(fileExt(f.name)));
    const subs = node.subfolders || {};
    Object.keys(subs).forEach((k) => collectExts(subs[k], set));
  }

  function populateTypeFilter() {
    const prev = typeFilter.value;
    const set = new Set();
    if (currentStructure) {
      const root = currentStructure[Object.keys(currentStructure)[0]];
      collectExts(root, set);
    }
    const hasNoExt = set.delete("");
    const exts = Array.from(set).sort();
    let html = '<option value="">All types</option>';
    html += exts
      .map((e) => '<option value="' + escapeHtml(e) + '">' + escapeHtml(e) + "</option>")
      .join("");
    if (hasNoExt) html += '<option value="__none__">(no extension)</option>';
    typeFilter.innerHTML = html;

    const desired = prev || pendingTypeFilter;
    if (
      desired &&
      Array.prototype.some.call(typeFilter.options, (o) => o.value === desired)
    ) {
      typeFilter.value = desired;
    }
    pendingTypeFilter = null;
  }

  function applyColumnVisibility() {
    const showSize = document.getElementById("show-size").checked;
    const showCreated = document.getElementById("show-created").checked;
    const showMod = document.getElementById("show-modified").checked;
    treeEl.querySelectorAll(".meta-size").forEach((e) => (e.style.display = showSize ? "" : "none"));
    treeEl.querySelectorAll(".meta-created").forEach((e) => (e.style.display = showCreated ? "" : "none"));
    treeEl.querySelectorAll(".meta-modified").forEach((e) => (e.style.display = showMod ? "" : "none"));
    const thSize = document.querySelector(".th-size");
    const thCreated = document.querySelector(".th-created");
    const thMod = document.querySelector(".th-modified");
    if (thSize) thSize.style.display = showSize ? "" : "none";
    if (thCreated) thCreated.style.display = showCreated ? "" : "none";
    if (thMod) thMod.style.display = showMod ? "" : "none";
  }

  // ---- ASCII export -----------------------------------------------------
  // `ancestors` is a list of booleans, one per level from the root down to this
  // node, where each entry records whether that ancestor was the last child of
  // its parent. The prefix is rebuilt from it at every level so indentation and
  // ├──/└── connectors accumulate correctly at any depth (mirrors the desktop).
  function asciiPrefix(ancestors) {
    let prefix = "";
    for (let i = 0; i < ancestors.length - 1; i++) {
      prefix += ancestors[i] ? "    " : "│   ";
    }
    if (ancestors.length) {
      prefix += ancestors[ancestors.length - 1] ? "└── " : "├── ";
    }
    return prefix;
  }

  function buildAscii(name, node, ancestors, lines, opts) {
    opts = opts || {};
    let dirLine = asciiPrefix(ancestors) + name + "/";
    if (opts.showSize) {
      dirLine += "  [" + countDescendants(node).files + " files]";
    }
    lines.push(dirLine);

    const subNames = Object.keys(node.subfolders || {}).sort((a, b) =>
      a.toLowerCase().localeCompare(b.toLowerCase())
    );
    const files = (node.files || [])
      .slice()
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

    const total = subNames.length + files.length;
    let idx = 0;
    subNames.forEach((key) => {
      const isLast = ++idx === total;
      buildAscii(key, node.subfolders[key], ancestors.concat(isLast), lines, opts);
    });
    files.forEach((file) => {
      const isLast = ++idx === total;
      let line = asciiPrefix(ancestors.concat(isLast)) + file.name;
      const extra = [];
      if (opts.showSize) extra.push(humanSize(file.size));
      if (opts.showCreated && file.created) extra.push(file.created);
      if (opts.showModified && file.modified) extra.push(file.modified);
      if (extra.length) line += "  (" + extra.join(", ") + ")";
      lines.push(line);
    });
  }

  // ---- Filters (name search + file type + excluded dirs) ----------------
  function applyFilters() {
    const q = treeSearch.value.trim().toLowerCase();
    const type = typeFilter.value;
    const showExcluded = showExcludedEl.checked;
    const rows = treeEl.querySelectorAll(".node-row");

    rows.forEach((r) => {
      const nameEl = r.querySelector(".node-name");
      const label = r.querySelector(".node-label");
      const name = nameEl.dataset.name || "";
      const isFile = nameEl.classList.contains("file");
      let visible = true;

      if (r.classList.contains("excluded-dir") && !showExcluded) visible = false;

      if (visible && type && isFile) {
        const ext = r.dataset.ext || "";
        if (type === "__none__") {
          if (ext !== "") visible = false;
        } else if (ext !== type) {
          visible = false;
        }
      }

      const original = label.dataset.text || label.textContent;
      if (visible && q) {
        const i = original.toLowerCase().indexOf(q);
        if (i >= 0) {
          label.innerHTML =
            escapeHtml(original.slice(0, i)) +
            "<mark>" +
            escapeHtml(original.slice(i, i + q.length)) +
            "</mark>" +
            escapeHtml(original.slice(i + q.length));
        } else {
          visible = false;
          label.textContent = original;
        }
      } else {
        label.textContent = original;
      }

      r.classList.toggle("hidden", !visible);
    });
  }

  // ---- Events -----------------------------------------------------------
  treeSearch.addEventListener("input", applyFilters);
  typeFilter.addEventListener("change", () => {
    applyFilters();
    saveSettings();
  });
  showExcludedEl.addEventListener("change", () => {
    applyFilters();
    saveSettings();
  });
  document.getElementById("show-size").addEventListener("change", () => {
    applyColumnVisibility();
    saveSettings();
  });
  document.getElementById("show-created").addEventListener("change", () => {
    applyColumnVisibility();
    saveSettings();
  });
  document.getElementById("show-modified").addEventListener("change", () => {
    applyColumnVisibility();
    saveSettings();
  });

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
    const opts = {
      showSize: document.getElementById("show-size").checked,
      showCreated: document.getElementById("show-created").checked,
      showModified: document.getElementById("show-modified").checked,
    };
    buildAscii(rootName, currentStructure[rootName], [], lines, opts);
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

  document.getElementById("clear-logs").addEventListener("click", () => {
    logsOutput.innerHTML = '<span class="empty">Processing logs will appear here.</span>';
    setDownloadEnabled("download-log", false);
  });
  document.getElementById("copy-logs").addEventListener("click", () => {
    const text = logsOutput.textContent || "";
    if (!text.trim()) {
      showToast("No logs to copy.", true);
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => showToast("Logs copied to clipboard."),
      () => showToast("Copy failed.", true)
    );
  });

  // ---- Tree snapshot save / load ---------------------------------------
  document.getElementById("save-snapshot").addEventListener("click", () => {
    if (!lastData) {
      showToast("Run the tools first — nothing to save yet.", true);
      return;
    }
    const snap = {
      type: "project-tools-runner-snapshot",
      version: 1,
      generatedAt: new Date().toISOString(),
      excludes: Array.from(lastExcludeSet),
      data: lastData,
    };
    triggerDownload("project_snapshot.json", JSON.stringify(snap, null, 2));
  });
  document.getElementById("load-snapshot").addEventListener("click", () =>
    document.getElementById("snapshot-input").click()
  );
  document.getElementById("snapshot-input").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const snap = JSON.parse(await file.text());
      const data = snap && snap.data ? snap.data : snap;
      if (!data || (!data.structure && !data.loader)) {
        throw new Error("Not a recognized snapshot file.");
      }
      if (snap && Array.isArray(snap.excludes)) data.excludes = snap.excludes;
      renderResults(data);
      setStatus("");
      showToast("Snapshot loaded.");
    } catch (err) {
      showToast(
        "Could not load snapshot: " + (err && err.message ? err.message : err),
        true
      );
    } finally {
      e.target.value = "";
    }
  });

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
    radio.addEventListener("change", () => {
      applyInputMode();
      saveSettings();
    });
  });
  applyInputMode();

  cancelBtn.addEventListener("click", () => {
    cancelRequested = true;
    setStatus("Cancelling...");
  });

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

    cancelRequested = false;
    runBtn.disabled = true;
    runBtn.textContent = "Running...";
    cancelBtn.classList.remove("hidden");
    showProgress();

    try {
      const pyodide = await ensurePyodide();
      let rootName;
      if (inputMode === "git") {
        const gh = parseGithubUrl(gitUrl);
        if (gh) {
          // Public GitHub repo: fetch via jsDelivr CDN — no proxy required.
          ({ rootName } = await fetchGithubViaJsdelivr(
            pyodide,
            gh.owner,
            gh.repo,
            gh.ref,
            excludeSet
          ));
        } else {
          // Other hosts: fall back to a client-side clone through the proxy.
          ({ rootName } = await cloneRepoToFs(
            pyodide,
            gitUrl,
            excludeSet,
            corsProxyEl.value.trim()
          ));
        }
      } else {
        ({ rootName } = selectedDirHandle
          ? await populateFsFromHandle(pyodide, selectedDirHandle, excludeSet)
          : await populateFs(pyodide, selectedFiles, excludeSet));
      }

      checkCancelled();
      setStatus("Running tools in your browser...");
      setIndeterminate();
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
      setStatus("");
      if (err && err.message === CANCELLED) {
        showToast("Cancelled.");
      } else {
        console.error(err);
        let msg = err && err.message ? err.message : String(err);
        if (inputMode === "git") {
          const isGithub = !!parseGithubUrl(gitUrl);
          if (msg === "jsdelivr-list-failed") {
            msg =
              "Couldn't find that GitHub repo or branch. Check the URL points to a public repo; for a non-default branch use the \u2026/tree/<branch> form.";
          } else if (/failed to fetch|networkerror|load failed|cors/i.test(msg)) {
            msg = isGithub
              ? "Couldn't download the repo (jsDelivr/network). Check your connection and that the repo is public, then try again."
              : "Couldn't reach the repo through the CORS proxy — it may be down or rate-limited. Try again, or set a different proxy under \u201CAdvanced: CORS proxy\u201D.";
          }
        }
        showToast("Failed: " + msg, true);
      }
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Run Tools";
      cancelBtn.classList.add("hidden");
      hideProgress();
    }
  });

  function renderResults(data) {
    lastData = data;
    lastExcludeSet = new Set(Array.isArray(data.excludes) ? data.excludes : []);
    setDownloadEnabled("save-snapshot", !!(data.structure || data.loader));

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

  // ---- Settings persistence (localStorage) -----------------------------
  function gatherSettings() {
    return {
      inputMode: getInputMode(),
      runStructure: document.getElementById("run-structure").checked,
      runLoader: document.getElementById("run-loader").checked,
      useDefaults: document.getElementById("use-defaults").checked,
      excludeDirs: document.getElementById("exclude-dirs").value,
      corsProxy: corsProxyEl.value,
      gitUrl: gitUrlEl.value,
      showSize: document.getElementById("show-size").checked,
      showCreated: document.getElementById("show-created").checked,
      showModified: document.getElementById("show-modified").checked,
      showExcluded: showExcludedEl.checked,
      typeFilter: typeFilter.value,
    };
  }
  function saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(gatherSettings()));
    } catch (e) {
      /* storage unavailable (private mode, quota) — non-fatal */
    }
  }
  function loadSettings() {
    let s;
    try {
      s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
    } catch (e) {
      s = null;
    }
    if (!s) return;
    const setChecked = (id, v) => {
      if (typeof v === "boolean") document.getElementById(id).checked = v;
    };
    if (s.inputMode) {
      const r = document.querySelector(
        'input[name="input-mode"][value="' + s.inputMode + '"]'
      );
      if (r) r.checked = true;
    }
    setChecked("run-structure", s.runStructure);
    setChecked("run-loader", s.runLoader);
    setChecked("use-defaults", s.useDefaults);
    setChecked("show-size", s.showSize);
    setChecked("show-created", s.showCreated);
    setChecked("show-modified", s.showModified);
    setChecked("show-excluded", s.showExcluded);
    if (typeof s.excludeDirs === "string")
      document.getElementById("exclude-dirs").value = s.excludeDirs;
    if (typeof s.corsProxy === "string") corsProxyEl.value = s.corsProxy;
    if (typeof s.gitUrl === "string") gitUrlEl.value = s.gitUrl;
    if (typeof s.typeFilter === "string" && s.typeFilter)
      pendingTypeFilter = s.typeFilter;
    applyInputMode();
  }

  ["run-structure", "run-loader", "use-defaults"].forEach((id) =>
    document.getElementById(id).addEventListener("change", saveSettings)
  );
  document.getElementById("exclude-dirs").addEventListener("input", saveSettings);
  corsProxyEl.addEventListener("input", saveSettings);
  gitUrlEl.addEventListener("input", saveSettings);

  document.getElementById("reset-settings").addEventListener("click", () => {
    try {
      localStorage.removeItem(SETTINGS_KEY);
    } catch (e) {
      /* ignore */
    }
    location.reload();
  });

  // ---- About modal ------------------------------------------------------
  const aboutModal = document.getElementById("about-modal");
  const aboutBtn = document.getElementById("about-btn");
  const aboutClose = document.getElementById("about-close");

  const backgroundEls = [
    document.querySelector(".app-header"),
    document.querySelector(".layout"),
  ].filter(Boolean);

  function openAbout() {
    aboutModal.classList.remove("hidden");
    backgroundEls.forEach((el) => el.setAttribute("inert", ""));
    aboutClose.focus();
  }
  function closeAbout() {
    aboutModal.classList.add("hidden");
    backgroundEls.forEach((el) => el.removeAttribute("inert"));
    aboutBtn.focus();
  }

  aboutBtn.addEventListener("click", openAbout);
  aboutClose.addEventListener("click", closeAbout);
  aboutModal.addEventListener("click", (e) => {
    if (e.target === aboutModal) closeAbout();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !aboutModal.classList.contains("hidden")) closeAbout();
  });

  loadSettings();
})();
