import { app, BrowserWindow, clipboard, dialog, ipcMain, nativeImage } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import type { AppConfig } from "../src/shared/types.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcessWithoutNullStreams | null = null;
let isQuitting = false;
const APP_ICON_RELATIVE_PATH = path.join("assets", "icons", "app-icon.png");

function getUserDataFile() {
  return path.join(app.getPath("userData"), "config.json");
}

function readAppConfig(): AppConfig {
  const configFile = getUserDataFile();
  const defaults: AppConfig = {
    outputDirectory: path.join(app.getPath("videos"), "ClipLab"),
    backendUrl: process.env.CLIPLAB_BACKEND_URL || DEFAULT_BACKEND_URL,
    douyinCookie: "",
    kuaishouCookie: ""
  };

  if (!existsSync(configFile)) {
    return defaults;
  }

  try {
    const raw = JSON.parse(readFileSync(configFile, "utf-8")) as Partial<AppConfig>;
    return {
      outputDirectory: raw.outputDirectory || defaults.outputDirectory,
      backendUrl: raw.backendUrl || defaults.backendUrl,
      douyinCookie: raw.douyinCookie || "",
      kuaishouCookie: raw.kuaishouCookie || ""
    };
  } catch {
    return defaults;
  }
}

function writeAppConfig(config: AppConfig) {
  const configFile = getUserDataFile();
  mkdirSync(path.dirname(configFile), { recursive: true });
  writeFileSync(configFile, JSON.stringify(config, null, 2), "utf-8");
}

function resolveBackendBinary() {
  const packagedRoot = process.resourcesPath;
  const binaryName = process.platform === "win32" ? "cliplab-backend.exe" : "cliplab-backend";
  return path.join(packagedRoot, "backend", "dist", binaryName);
}

function resolveAppIconPath() {
  const candidates = app.isPackaged
    ? [
        path.join(app.getAppPath(), "dist", APP_ICON_RELATIVE_PATH),
        path.join(process.resourcesPath, "app.asar.unpacked", "dist", APP_ICON_RELATIVE_PATH),
        path.join(process.resourcesPath, "dist", APP_ICON_RELATIVE_PATH)
      ]
    : [
        path.join(process.cwd(), "public", APP_ICON_RELATIVE_PATH),
        path.join(process.cwd(), "dist", APP_ICON_RELATIVE_PATH)
      ];

  return candidates.find((candidate) => existsSync(candidate));
}

function getPackagedBackendPidFile() {
  return path.join(app.getPath("userData"), "run", "backend.pid");
}

function processExists(pid: number) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function terminateProcess(pid: number, reason: string) {
  if (!Number.isInteger(pid) || pid <= 0 || !processExists(pid)) {
    return;
  }

  console.log(`[cleanup] stopping ${reason} (pid ${pid})`);
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    return;
  }

  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (!processExists(pid)) {
      return;
    }
    await delay(150);
  }

  console.log(`[cleanup] force killing ${reason} (pid ${pid})`);
  try {
    process.kill(pid, "SIGKILL");
  } catch {
    return;
  }
}

async function cleanupStaleBackendPidFile() {
  const pidFile = getPackagedBackendPidFile();
  if (!existsSync(pidFile)) {
    return;
  }

  const raw = readFileSync(pidFile, "utf-8").trim();
  const pid = Number.parseInt(raw, 10);
  if (Number.isInteger(pid)) {
    await terminateProcess(pid, "stale packaged backend");
  }
  rmSync(pidFile, { force: true });
}

function stopBackendProcess() {
  if (!backendProcess || backendProcess.exitCode !== null) {
    backendProcess = null;
    return;
  }

  const processToStop = backendProcess;
  processToStop.kill("SIGTERM");
  setTimeout(() => {
    if (processToStop.exitCode === null) {
      processToStop.kill("SIGKILL");
    }
  }, 4000).unref();
}

function createBackendProcess(config: AppConfig) {
  if (process.env.CLIPLAB_BACKEND_URL || !app.isPackaged) {
    return;
  }

  const binaryPath = resolveBackendBinary();
  if (!existsSync(binaryPath)) {
    console.warn(`ClipLab backend binary not found: ${binaryPath}`);
    return;
  }

  backendProcess = spawn(binaryPath, [], {
    cwd: path.dirname(binaryPath),
    env: {
      ...process.env,
      CLIPLAB_APP_DATA: app.getPath("userData"),
      CLIPLAB_BACKEND_URL: config.backendUrl,
      CLIPLAB_PID_FILE: getPackagedBackendPidFile()
    }
  });

  backendProcess.once("exit", () => {
    backendProcess = null;
  });

  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk.toString()}`);
  });

  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk.toString()}`);
  });
}

async function createWindow() {
  const config = readAppConfig();
  const iconPath = resolveAppIconPath();
  const icon = iconPath ? nativeImage.createFromPath(iconPath) : undefined;

  await cleanupStaleBackendPidFile();

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1200,
    minHeight: 720,
    title: "ClipLab",
    icon,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (process.platform === "darwin" && icon && !icon.isEmpty()) {
    app.dock?.setIcon(icon);
  }

  if (!app.isPackaged) {
    mainWindow.webContents.on(
      "did-fail-load",
      (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
        console.error(
          `[renderer:load-failed] code=${errorCode} mainFrame=${isMainFrame} url=${validatedURL} error=${errorDescription}`
        );
      }
    );

    mainWindow.webContents.on("render-process-gone", (_event, details) => {
      console.error(`[renderer:gone] reason=${details.reason} exitCode=${details.exitCode}`);
    });
  }

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else if (!app.isPackaged) {
    mainWindow.loadFile(path.join(process.cwd(), "dist", "index.html"));
  } else {
    mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
  }

  createBackendProcess(config);
}

app.whenReady().then(async () => {
  ipcMain.handle("config:get", () => readAppConfig());
  ipcMain.handle("config:set", (_event, nextConfig: AppConfig) => {
    writeAppConfig(nextConfig);
    return nextConfig;
  });
  ipcMain.handle("clipboard:read-text", () => clipboard.readText());
  ipcMain.handle("dialog:pick-directory", async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openDirectory", "createDirectory"]
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("dialog:pick-video", async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openFile"],
      filters: [
        {
          name: "Video",
          extensions: ["mp4", "mov", "mkv", "avi", "webm"]
        }
      ]
    });
    return result.canceled ? null : result.filePaths[0];
  });

  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  if (app.isPackaged) {
    stopBackendProcess();
  }
});

app.on("quit", () => {
  if (app.isPackaged) {
    stopBackendProcess();
  }
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    if (!isQuitting) {
      stopBackendProcess();
      app.quit();
    }
  });
}
