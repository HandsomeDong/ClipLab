import { app, BrowserWindow, clipboard, dialog, ipcMain, nativeImage, shell } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import type { AppConfig, BackendStartupState } from "../src/shared/types.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
const BACKEND_STARTUP_CHANNEL = "backend:startup-state";
const BACKEND_HEALTH_RETRY_MS = 1200;
const BACKEND_HEALTH_STABLE_MS = 4000;
const BACKEND_HEALTH_TIMEOUT_MS = 1500;
let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcessWithoutNullStreams | null = null;
let isQuitting = false;
const APP_ICON_RELATIVE_PATH = path.join("assets", "icons", "app-icon.png");
type BackendStartupSnapshot = Omit<BackendStartupState, "updatedAt">;

let backendHealthTimer: NodeJS.Timeout | null = null;
let backendHealthCheckInFlight = false;
let backendHealthAttempt = 0;
let backendStartupStartedAt = 0;
let backendLastOutputLine = "";
let backendStartupState: BackendStartupState = createBackendStartupState({
  phase: "checking",
  label: "检测后端状态",
  detail: "应用正在准备后端服务。",
  progress: 5,
  managed: false
});

function getUserDataFile() {
  return path.join(app.getPath("userData"), "config.json");
}

function createBackendStartupState(snapshot: BackendStartupSnapshot): BackendStartupState {
  return {
    ...snapshot,
    updatedAt: new Date().toISOString()
  };
}

function currentBackendStartupSnapshot(): BackendStartupSnapshot {
  const { updatedAt: _updatedAt, ...snapshot } = backendStartupState;
  return snapshot;
}

function broadcastBackendStartupState() {
  for (const window of BrowserWindow.getAllWindows()) {
    if (!window.isDestroyed()) {
      window.webContents.send(BACKEND_STARTUP_CHANNEL, backendStartupState);
    }
  }
}

function setBackendStartupState(snapshot: BackendStartupSnapshot) {
  backendStartupState = createBackendStartupState(snapshot);
  broadcastBackendStartupState();
}

function patchBackendStartupState(patch: Partial<BackendStartupSnapshot>) {
  backendStartupState = createBackendStartupState({
    ...currentBackendStartupSnapshot(),
    ...patch
  });
  broadcastBackendStartupState();
}

function isManagedBackendMode() {
  return app.isPackaged && !process.env.CLIPLAB_BACKEND_URL;
}

function getBackendHealthUrl(backendUrl: string) {
  return `${backendUrl.replace(/\/+$/, "")}/api/health`;
}

function getStartupElapsedSeconds() {
  if (!backendStartupStartedAt) {
    return 0;
  }
  return Math.max(0, Math.floor((Date.now() - backendStartupStartedAt) / 1000));
}

function rememberBackendOutput(chunk: string) {
  const lines = chunk
    .split(/\r?\n/)
    .map((line) => line.replace(/\u001b\[[0-9;]*m/g, "").trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return;
  }

  backendLastOutputLine = lines[lines.length - 1];
  if (backendStartupState.phase === "waiting") {
    const elapsed = getStartupElapsedSeconds();
    patchBackendStartupState({
      detail: elapsed
        ? `后端进程已启动，正在等待 HTTP 服务响应（${elapsed}s）。最近输出：${backendLastOutputLine}`
        : `后端进程已启动，正在等待 HTTP 服务响应。最近输出：${backendLastOutputLine}`
    });
  }
}

function stopBackendHealthMonitor() {
  if (backendHealthTimer) {
    clearTimeout(backendHealthTimer);
    backendHealthTimer = null;
  }
}

function scheduleBackendHealthCheck(config: AppConfig, delayMs: number) {
  stopBackendHealthMonitor();
  backendHealthTimer = setTimeout(() => {
    void runBackendHealthCheck(config);
  }, delayMs);
  backendHealthTimer.unref();
}

async function isBackendHealthy(backendUrl: string) {
  try {
    const response = await fetch(getBackendHealthUrl(backendUrl), {
      signal: AbortSignal.timeout(BACKEND_HEALTH_TIMEOUT_MS)
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function runBackendHealthCheck(config: AppConfig) {
  if (backendHealthCheckInFlight) {
    return;
  }

  backendHealthCheckInFlight = true;
  backendHealthAttempt += 1;

  try {
    const healthy = await isBackendHealthy(config.backendUrl);
    if (healthy) {
      setBackendStartupState({
        phase: "online",
        label: "后端已就绪",
        detail: isManagedBackendMode()
          ? "内置后端已启动完成，桌面端可以正常使用。"
          : `已连接到外部后端 ${config.backendUrl}。`,
        progress: 100,
        managed: isManagedBackendMode()
      });
      scheduleBackendHealthCheck(config, BACKEND_HEALTH_STABLE_MS);
      return;
    }

    if (isManagedBackendMode()) {
      if (backendProcess && backendProcess.exitCode === null) {
        const elapsed = getStartupElapsedSeconds();
        const progress = Math.min(92, 48 + backendHealthAttempt * 6);
        const detail = backendLastOutputLine
          ? `后端进程已启动，正在等待 HTTP 服务响应（${elapsed}s）。最近输出：${backendLastOutputLine}`
          : `后端进程已启动，正在等待 HTTP 服务响应（${elapsed}s）。`;
        setBackendStartupState({
          phase: "waiting",
          label: "等待后端就绪",
          detail,
          progress,
          managed: true
        });
      } else if (backendStartupState.phase !== "error") {
        setBackendStartupState({
          phase: "offline",
          label: "后端未连接",
          detail: "未检测到可用的内置后端进程。",
          progress: 0,
          managed: true
        });
      }
    } else {
      const wasOnline = backendStartupState.phase === "online";
      const elapsed = getStartupElapsedSeconds();
      setBackendStartupState({
        phase: wasOnline ? "offline" : "waiting_external",
        label: wasOnline ? "后端已断开" : "等待外部后端",
        detail: wasOnline
          ? `与外部后端 ${config.backendUrl} 的连接已断开。`
          : `正在连接外部后端 ${config.backendUrl}（${elapsed}s）。`,
        progress: wasOnline ? 0 : Math.min(88, 22 + backendHealthAttempt * 5),
        managed: false
      });
    }

    scheduleBackendHealthCheck(config, BACKEND_HEALTH_RETRY_MS);
  } finally {
    backendHealthCheckInFlight = false;
  }
}

function readAppConfig(): AppConfig {
  const configFile = getUserDataFile();
  const defaults: AppConfig = {
    downloadOutputDirectory: path.join(app.getPath("videos"), "ClipLab"),
    backendUrl: process.env.CLIPLAB_BACKEND_URL || DEFAULT_BACKEND_URL,
    douyinCookie: "",
    kuaishouCookie: ""
  };

  if (!existsSync(configFile)) {
    return defaults;
  }

  try {
    const raw = JSON.parse(readFileSync(configFile, "utf-8")) as Partial<AppConfig>;
    const legacyOutputDirectory =
      typeof (raw as { outputDirectory?: string }).outputDirectory === "string"
        ? (raw as { outputDirectory?: string }).outputDirectory
        : "";
    return {
      downloadOutputDirectory: raw.downloadOutputDirectory || legacyOutputDirectory || defaults.downloadOutputDirectory,
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
  stopBackendHealthMonitor();
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

async function initializeBackendService(config: AppConfig) {
  stopBackendHealthMonitor();
  backendHealthAttempt = 0;
  backendLastOutputLine = "";
  backendStartupStartedAt = Date.now();

  if (!isManagedBackendMode()) {
    setBackendStartupState({
      phase: "waiting_external",
      label: "等待外部后端",
      detail: `正在连接外部后端 ${config.backendUrl}。`,
      progress: 18,
      managed: false
    });
    scheduleBackendHealthCheck(config, 0);
    return;
  }

  if (backendProcess && backendProcess.exitCode === null) {
    setBackendStartupState({
      phase: "waiting",
      label: "检查后端服务",
      detail: "检测到已有内置后端进程，正在确认服务状态。",
      progress: 50,
      managed: true
    });
    scheduleBackendHealthCheck(config, 0);
    return;
  }

  setBackendStartupState({
    phase: "cleaning",
    label: "清理残留进程",
    detail: "正在检查上一次退出后遗留的后端进程。",
    progress: 8,
    managed: true
  });
  await cleanupStaleBackendPidFile();

  setBackendStartupState({
    phase: "checking",
    label: "检查后端程序",
    detail: "正在定位随应用打包的后端服务。",
    progress: 18,
    managed: true
  });

  const binaryPath = resolveBackendBinary();
  if (!existsSync(binaryPath)) {
    const detail = `未找到内置后端程序：${binaryPath}`;
    console.warn(`ClipLab backend binary not found: ${binaryPath}`);
    setBackendStartupState({
      phase: "error",
      label: "后端启动失败",
      detail,
      progress: 100,
      managed: true
    });
    return;
  }

  setBackendStartupState({
    phase: "starting",
    label: "启动后端进程",
    detail: `正在启动 ${path.basename(binaryPath)}。`,
    progress: 34,
    managed: true
  });

  const child = spawn(binaryPath, [], {
    cwd: path.dirname(binaryPath),
    env: {
      ...process.env,
      CLIPLAB_APP_DATA: app.getPath("userData"),
      CLIPLAB_BACKEND_URL: config.backendUrl,
      CLIPLAB_PID_FILE: getPackagedBackendPidFile()
    }
  });

  backendProcess = child;

  child.once("spawn", () => {
    setBackendStartupState({
      phase: "waiting",
      label: "等待后端就绪",
      detail: "后端进程已启动，正在等待 HTTP 服务响应。",
      progress: 50,
      managed: true
    });
    scheduleBackendHealthCheck(config, 0);
  });

  child.once("error", (error) => {
    stopBackendHealthMonitor();
    backendProcess = null;
    setBackendStartupState({
      phase: "error",
      label: "后端启动失败",
      detail: `无法启动内置后端：${error.message}`,
      progress: 100,
      managed: true
    });
  });

  child.once("exit", (code, signal) => {
    stopBackendHealthMonitor();
    backendProcess = null;
    if (isQuitting) {
      return;
    }

    const reason = code !== null ? `退出码 ${code}` : `信号 ${signal ?? "unknown"}`;
    setBackendStartupState({
      phase: "error",
      label: "后端进程已退出",
      detail: backendLastOutputLine ? `${reason}。最近输出：${backendLastOutputLine}` : reason,
      progress: 100,
      managed: true
    });
  });

  child.stdout.on("data", (chunk) => {
    const text = chunk.toString();
    rememberBackendOutput(text);
    process.stdout.write(`[backend] ${text}`);
  });

  child.stderr.on("data", (chunk) => {
    const text = chunk.toString();
    rememberBackendOutput(text);
    process.stderr.write(`[backend] ${text}`);
  });
}

async function createWindow() {
  const config = readAppConfig();
  const iconPath = resolveAppIconPath();
  const icon = iconPath ? nativeImage.createFromPath(iconPath) : undefined;

  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1120,
    minHeight: 680,
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

  mainWindow.webContents.once("did-finish-load", () => {
    mainWindow?.webContents.send(BACKEND_STARTUP_CHANNEL, backendStartupState);
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else if (!app.isPackaged) {
    mainWindow.loadFile(path.join(process.cwd(), "dist", "index.html"));
  } else {
    mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
  }

  void initializeBackendService(config);
}

app.whenReady().then(async () => {
  ipcMain.handle("config:get", () => readAppConfig());
  ipcMain.handle("backend:start-state:get", () => backendStartupState);
  ipcMain.handle("config:set", (_event, nextConfig: AppConfig) => {
    writeAppConfig(nextConfig);
    return nextConfig;
  });
  ipcMain.handle("clipboard:read-text", () => clipboard.readText());
  ipcMain.handle("shell:open-folder", async (_event, targetPath: string) => {
    if (!targetPath) {
      return;
    }
    if (existsSync(targetPath)) {
      if (statSync(targetPath).isDirectory()) {
        const errorMessage = await shell.openPath(targetPath);
        if (errorMessage) {
          throw new Error(errorMessage);
        }
        return;
      }
      shell.showItemInFolder(targetPath);
      return;
    }
    const errorMessage = await shell.openPath(path.dirname(targetPath));
    if (errorMessage) {
      throw new Error(errorMessage);
    }
  });
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
