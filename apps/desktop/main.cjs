const { app, BrowserWindow, dialog } = require("electron");
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");
const { spawn } = require("node:child_process");

const API_PORT = "8001";
const WEB_PORT = "3001";
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

const childProcesses = new Set();

function isWindows() {
  return process.platform === "win32";
}

function command(name) {
  return isWindows() ? `${name}.cmd` : name;
}

function repoRoot() {
  return process.env.ADALA_REPO_ROOT || path.resolve(__dirname, "../..");
}

function isPackaged() {
  return app.isPackaged;
}

function readJsonIfExists(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, "utf8"));
    }
  } catch {
    return {};
  }
  return {};
}

function desktopSettingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function ensureDesktopSettings() {
  const settingsPath = desktopSettingsPath();
  if (!fs.existsSync(settingsPath)) {
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
    fs.writeFileSync(
      settingsPath,
      JSON.stringify(
        {
          ollamaBaseUrl: "https://your-remote-ollama.example.com",
          ollamaModel: "qwen3:1.7b",
          ollamaApiKey: "",
          ragLlmEnabled: false
        },
        null,
        2
      )
    );
  }
  return readJsonIfExists(settingsPath);
}

function modelSettings() {
  const fileSettings = ensureDesktopSettings();
  const ollamaBaseUrl =
    process.env.OLLAMA_BASE_URL || fileSettings.ollamaBaseUrl || "https://your-remote-ollama.example.com";
  return {
    ollamaBaseUrl,
    ollamaModel: process.env.OLLAMA_MODEL || fileSettings.ollamaModel || "qwen3:1.7b",
    ollamaApiKey: process.env.OLLAMA_API_KEY || fileSettings.ollamaApiKey || "",
    ragLlmEnabled: String(process.env.RAG_LLM_ENABLED || fileSettings.ragLlmEnabled || "false")
  };
}

function spawnManaged(label, executable, args, options) {
  const child = spawn(executable, args, {
    stdio: isPackaged() ? "ignore" : "inherit",
    windowsHide: true,
    ...options
  });
  childProcesses.add(child);
  child.once("exit", () => childProcesses.delete(child));
  child.once("error", (error) => {
    dialog.showErrorBox(`${label} failed to start`, error.message);
  });
  return child;
}

function packagedApiExecutable() {
  const candidates = [
    path.join(process.resourcesPath, "api", "adala-api.exe"),
    path.join(process.resourcesPath, "api", "adala-api", "adala-api.exe"),
    path.join(process.resourcesPath, "api", "adala-api"),
    path.join(process.resourcesPath, "api", "adala-api", "adala-api")
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function startApi() {
  const settings = modelSettings();
  const env = {
    ...process.env,
    ADALA_API_HOST: "127.0.0.1",
    ADALA_API_PORT: API_PORT,
    APP_ENV: "desktop",
    CORS_ORIGINS: `${WEB_URL},http://localhost:${WEB_PORT}`,
    DATA_DIR: path.join(app.getPath("userData"), "data"),
    VECTOR_BACKEND: "local",
    LLM_PROVIDER: "ollama",
    RAG_LLM_ENABLED: settings.ragLlmEnabled,
    OLLAMA_BASE_URL: settings.ollamaBaseUrl,
    OLLAMA_MODEL: settings.ollamaModel,
    OLLAMA_API_KEY: settings.ollamaApiKey,
    OCR_ENABLED: "true",
    OCR_ON_UPLOAD: "true"
  };

  if (settings.ollamaBaseUrl.includes("your-remote-ollama.example.com")) {
    dialog.showMessageBox({
      type: "warning",
      title: "Remote model endpoint not configured",
      message: "Adala AI is configured for remote model mode, but no remote Ollama URL is set yet.",
      detail: `Edit this file and set ollamaBaseUrl:\n${desktopSettingsPath()}`
    });
  }

  if (isPackaged()) {
    const apiExe = packagedApiExecutable();
    if (!apiExe) {
      dialog.showErrorBox(
        "Backend is missing",
        "The packaged API executable was not found. Rebuild the desktop installer after creating apps/api/dist/adala-api."
      );
      return;
    }
    spawnManaged("Adala API", apiExe, [], { env });
    return;
  }

  const root = repoRoot();
  const apiDir = path.join(root, "apps", "api");
  const venvPython = isWindows()
    ? path.join(apiDir, ".venv", "Scripts", "python.exe")
    : path.join(apiDir, ".venv", "bin", "python");
  const python = fs.existsSync(venvPython) ? venvPython : "python";
  spawnManaged("Adala API", python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", API_PORT], {
    cwd: apiDir,
    env
  });
}

function packagedWebServer() {
  const candidates = [
    path.join(process.resourcesPath, "web", "apps", "web", "server.js"),
    path.join(process.resourcesPath, "web", "server.js")
  ];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function startWeb() {
  const env = {
    ...process.env,
    PORT: WEB_PORT,
    HOSTNAME: "127.0.0.1",
    INTERNAL_API_BASE_URL: API_URL,
    NEXT_PUBLIC_API_BASE_URL: `${API_URL}/api`
  };

  if (isPackaged()) {
    const serverScript = packagedWebServer();
    if (!serverScript) {
      dialog.showErrorBox(
        "Web UI is missing",
        "The packaged Next.js server was not found. Run npm run build:web before building the desktop installer."
      );
      return;
    }
    spawnManaged("Adala Web", process.execPath, [serverScript], {
      env: { ...env, ELECTRON_RUN_AS_NODE: "1" },
      cwd: path.dirname(serverScript)
    });
    return;
  }

  const webDir = path.join(repoRoot(), "apps", "web");
  spawnManaged("Adala Web", command("npm"), ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", WEB_PORT], {
    cwd: webDir,
    env
  });
}

function waitForUrl(url, timeoutMs = 60000) {
  const started = Date.now();
  const client = url.startsWith("https:") ? https : http;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = client.get(url, (response) => {
        response.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - started > timeoutMs) {
          reject(new Error(`Timed out waiting for ${url}`));
          return;
        }
        setTimeout(tick, 750);
      });
      req.setTimeout(3000, () => {
        req.destroy();
      });
    };
    tick();
  });
}

async function createWindow() {
  startApi();
  startWeb();

  await waitForUrl(WEB_URL).catch((error) => {
    dialog.showErrorBox("Adala AI failed to start", error.message);
  });

  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1120,
    minHeight: 760,
    backgroundColor: "#06080d",
    title: "Adala AI",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  await window.loadURL(WEB_URL);
}

app.whenReady().then(createWindow);

app.on("before-quit", () => {
  for (const child of childProcesses) {
    if (!child.killed) {
      child.kill();
    }
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
