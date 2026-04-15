#!/usr/bin/env node

import { existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";

const projectRoot = process.cwd();
const backendRoot = path.join(projectRoot, "backend");
const entryFile = path.join(backendRoot, "cliplab_backend", "__main__.py");
const distDir = path.join(backendRoot, "dist");
const buildRoot = path.join(backendRoot, "build", "pyinstaller");
const binaryName = process.platform === "win32" ? "cliplab-backend.exe" : "cliplab-backend";
const binaryPath = path.join(distDir, binaryName);
const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const help = args.includes("--help") || args.includes("-h");

function printUsage() {
  console.log(`Usage: node scripts/build-backend-binary.mjs [--dry-run]

Build the packaged Python backend binary for the current host platform and architecture.

Options:
  --dry-run   Print the PyInstaller command without running it
  --help      Show this help message`);
}

function run(command, commandArgs) {
  console.log(`> ${command} ${commandArgs.join(" ")}`);
  if (dryRun) {
    return;
  }

  const result = spawnSync(command, commandArgs, {
    cwd: projectRoot,
    stdio: "inherit"
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

if (help) {
  printUsage();
  process.exit(0);
}

if (!existsSync(entryFile)) {
  console.error(`Backend entry file not found: ${entryFile}`);
  process.exit(1);
}

mkdirSync(distDir, { recursive: true });
mkdirSync(buildRoot, { recursive: true });

if (existsSync(binaryPath) && !dryRun) {
  rmSync(binaryPath, { force: true });
}

const pyInstallerArgs = [
  "run",
  "--project",
  "backend",
  "--with",
  "pyinstaller",
  "pyinstaller",
  "--noconfirm",
  "--clean",
  "--onefile",
  "--name",
  binaryName.replace(/\.exe$/u, ""),
  "--distpath",
  distDir,
  "--workpath",
  path.join(buildRoot, "work"),
  "--specpath",
  path.join(buildRoot, "spec"),
  "--paths",
  backendRoot,
  "--hidden-import",
  "h11",
  "--hidden-import",
  "uvicorn.loops.asyncio",
  "--hidden-import",
  "uvicorn.protocols.http.h11_impl",
  "--hidden-import",
  "uvicorn.lifespan.on",
  "--collect-all",
  "imageio_ffmpeg",
  entryFile
];

run("uv", pyInstallerArgs);

if (!dryRun && !existsSync(binaryPath)) {
  console.error(`Expected backend binary was not generated: ${binaryPath}`);
  process.exit(1);
}

if (!dryRun) {
  console.log(`Backend binary ready: ${binaryPath}`);
}
