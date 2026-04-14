import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";

const projectRoot = process.cwd();
const runDir = path.join(projectRoot, ".run");
const pidFile = path.join(runDir, "backend-dev.pid");
const backendPort = process.env.CLIPLAB_BACKEND_PORT || "8765";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function terminatePid(pid, reason) {
  if (!Number.isInteger(pid) || pid <= 0 || !processExists(pid)) {
    return false;
  }

  console.log(`[dev:clean] stopping ${reason} (pid ${pid})`);
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    return false;
  }

  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (!processExists(pid)) {
      return true;
    }
    await sleep(150);
  }

  console.log(`[dev:clean] force killing ${reason} (pid ${pid})`);
  try {
    process.kill(pid, "SIGKILL");
  } catch {
    return false;
  }

  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (!processExists(pid)) {
      return true;
    }
    await sleep(100);
  }

  return !processExists(pid);
}

function readPidFromFile(filePath) {
  if (!existsSync(filePath)) {
    return null;
  }

  const raw = readFileSync(filePath, "utf-8").trim();
  const pid = Number.parseInt(raw, 10);
  return Number.isInteger(pid) ? pid : null;
}

function unlinkIfPresent(filePath) {
  if (existsSync(filePath)) {
    rmSync(filePath, { force: true });
  }
}

function describePid(pid) {
  if (process.platform === "win32") {
    return "";
  }

  const result = spawnSync("ps", ["-p", String(pid), "-o", "command="], {
    encoding: "utf-8"
  });
  if (result.status !== 0) {
    return "";
  }
  return result.stdout.trim();
}

function findClipLabPortOwners(port) {
  if (process.platform === "win32") {
    return [];
  }

  const result = spawnSync("lsof", ["-nP", "-tiTCP:" + port, "-sTCP:LISTEN"], { encoding: "utf-8" });
  if (result.error || result.status === 1) {
    return [];
  }

  const pids = result.stdout
    .split(/\s+/)
    .map((value) => Number.parseInt(value, 10))
    .filter((value) => Number.isInteger(value));

  return [...new Set(pids)].map((pid) => ({ pid, command: describePid(pid) }));
}

function isClipLabBackendCommand(command) {
  return (
    command.includes("cliplab_backend.main:app") ||
    command.includes("cliplab-backend") ||
    (command.includes("uvicorn") && command.includes("8765"))
  );
}

async function cleanupPidFile() {
  const pid = readPidFromFile(pidFile);
  if (pid !== null) {
    await terminatePid(pid, "tracked ClipLab backend");
  }
  unlinkIfPresent(pidFile);
}

async function cleanupPortOwners() {
  const owners = findClipLabPortOwners(backendPort);
  for (const owner of owners) {
    if (isClipLabBackendCommand(owner.command)) {
      await terminatePid(owner.pid, "stale ClipLab listener");
      continue;
    }

    throw new Error(
      `Port ${backendPort} is occupied by a non-ClipLab process: ${owner.command || `pid ${owner.pid}`}`
    );
  }
}

async function main() {
  mkdirSync(runDir, { recursive: true });
  await cleanupPidFile();
  await cleanupPortOwners();
  unlinkIfPresent(pidFile);
}

main().catch((error) => {
  console.error(`[dev:clean] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
