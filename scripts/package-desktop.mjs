#!/usr/bin/env node

import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";

const projectRoot = process.cwd();
const args = process.argv.slice(2);
const help = args.includes("--help") || args.includes("-h");
const dryRun = args.includes("--dry-run");

function getOption(name) {
  const prefix = `--${name}=`;
  const value = args.find((arg) => arg.startsWith(prefix));
  return value ? value.slice(prefix.length) : null;
}

function printUsage() {
  console.log(`Usage: node scripts/package-desktop.mjs [--platform=mac|win] [--dry-run]

Package the Electron app for the current host platform. The script will:
1. build renderer and Electron main/preload files
2. build the Python backend binary for the same host platform/arch
3. invoke electron-builder with the matching target

Options:
  --platform   Target platform. Defaults to the current host platform
  --dry-run    Print commands without running them
  --help       Show this help message`);
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

function resolveHostPlatform() {
  if (process.platform === "darwin") {
    return "mac";
  }
  if (process.platform === "win32") {
    return "win";
  }
  return null;
}

function resolveHostArch() {
  if (process.arch === "arm64" || process.arch === "x64") {
    return process.arch;
  }
  return process.arch;
}

function npmCommand() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

function electronBuilderCommand() {
  return process.platform === "win32"
    ? path.join("node_modules", ".bin", "electron-builder.cmd")
    : path.join(".", "node_modules", ".bin", "electron-builder");
}

function binaryPathForHost() {
  const binaryName = process.platform === "win32" ? "cliplab-backend.exe" : "cliplab-backend";
  return path.join(projectRoot, "backend", "dist", binaryName);
}

if (help) {
  printUsage();
  process.exit(0);
}

const hostPlatform = resolveHostPlatform();
if (!hostPlatform) {
  console.error(`Unsupported host platform for packaging: ${process.platform}`);
  process.exit(1);
}

const requestedPlatform = getOption("platform") ?? hostPlatform;
if (!["mac", "win"].includes(requestedPlatform)) {
  console.error(`Unsupported target platform: ${requestedPlatform}`);
  process.exit(1);
}

if (requestedPlatform !== hostPlatform) {
  console.error(
    `Refusing to package ${requestedPlatform} from ${hostPlatform}. ` +
      "ClipLab bundles a native Python backend binary, so each platform should be packaged on a matching native host."
  );
  process.exit(1);
}

const hostArch = resolveHostArch();
const targetArgs =
  requestedPlatform === "mac"
    ? ["--mac", "dmg", `--${hostArch}`]
    : ["--win", "nsis", `--${hostArch}`];

run("node", ["scripts/prepare-app-icons.mjs", `--platform=${requestedPlatform}`, ...(dryRun ? ["--dry-run"] : [])]);

run(npmCommand(), ["run", "build"]);
run("node", ["scripts/build-backend-binary.mjs", ...(dryRun ? ["--dry-run"] : [])]);

const backendBinaryPath = binaryPathForHost();
if (!dryRun && !existsSync(backendBinaryPath)) {
  console.error(`Backend binary not found after build: ${backendBinaryPath}`);
  process.exit(1);
}

run(electronBuilderCommand(), targetArgs);
