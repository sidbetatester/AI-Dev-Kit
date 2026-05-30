(function () {
  "use strict";

  const form = document.getElementById("analyze-form");
  const runBtn = document.getElementById("run-btn");
  const summaryEl = document.getElementById("summary");
  const treeEl = document.getElementById("tree");
  const filesOutput = document.getElementById("files-output");
  const filesStats = document.getElementById("files-stats");
  const logsOutput = document.getElementById("logs-output");
  const treeSearch = document.getElementById("tree-search");
  const toast = document.getElementById("toast");

  let currentStructure = null;
  let currentRootName = "";

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

  function showToast(message, isError) {
    toast.textContent = message;
    toast.classList.toggle("error", !!isError);
    toast.classList.remove("hidden");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  function setDownload(id, token, kind, enabled) {
    const el = document.getElementById(id);
    if (enabled) {
      el.href = "/api/download/" + token + "/" + kind;
      el.classList.remove("disabled");
    } else {
      el.href = "#";
      el.classList.add("disabled");
    }
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
      treeEl.innerHTML = '<p class="empty">Run the tools to see your project structure here.</p>';
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

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("project-file");
    if (!fileInput.files.length) {
      showToast("Choose a .zip file first.", true);
      return;
    }

    const fd = new FormData();
    fd.append("project", fileInput.files[0]);
    fd.append("run_loader", document.getElementById("run-loader").checked);
    fd.append("run_structure", document.getElementById("run-structure").checked);
    fd.append("use_default_excludes", document.getElementById("use-defaults").checked);
    fd.append("exclude_dirs", document.getElementById("exclude-dirs").value);

    runBtn.disabled = true;
    runBtn.textContent = "Running...";

    try {
      const res = await fetch("/api/analyze", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Something went wrong.", true);
        return;
      }
      renderResults(data);
      showToast("Analysis complete.");
    } catch (err) {
      showToast("Request failed: " + err.message, true);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Run Tools";
    }
  });

  function renderResults(data) {
    const token = data.token;

    // Structure
    if (data.structure) {
      currentStructure = data.structure;
      currentRootName = data.root_name;
      renderTree();
      setDownload("download-json", token, "json", true);
    } else {
      currentStructure = null;
      renderTree();
      setDownload("download-json", token, "json", false);
    }

    // Loader
    if (data.loader) {
      const l = data.loader;
      filesOutput.textContent =
        l.preview + (l.truncated ? "\n\n... (truncated — download the full file) ..." : "");
      filesStats.textContent =
        l.processed +
        " files processed · " +
        l.skipped +
        " skipped · " +
        l.total_chars.toLocaleString() +
        " characters";
      setDownload("download-text", token, "text", true);
      setDownload("download-log", token, "log", true);
    } else {
      filesOutput.innerHTML = '<span class="empty">File loader was not run.</span>';
      filesStats.textContent = "";
      setDownload("download-text", token, "text", false);
      setDownload("download-log", token, "log", false);
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
