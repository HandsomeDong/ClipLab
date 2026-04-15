#!/usr/bin/env node

import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import pngToIco from "png-to-ico";

const projectRoot = process.cwd();
const args = process.argv.slice(2);
const help = args.includes("--help") || args.includes("-h");
const dryRun = args.includes("--dry-run");

const sourceIconPath = path.join(projectRoot, "public", "assets", "icons", "app-icon.png");
const outputRoot = path.join(projectRoot, ".build-resources", "icons");
const macIconsetDir = path.join(outputRoot, "icon.iconset");
const macIconPath = path.join(outputRoot, "icon.icns");
const winIconPath = path.join(outputRoot, "icon.ico");

function getOption(name) {
  const prefix = `--${name}=`;
  const value = args.find((arg) => arg.startsWith(prefix));
  return value ? value.slice(prefix.length) : null;
}

function printUsage() {
  console.log(`Usage: node scripts/prepare-app-icons.mjs [--platform=mac|win|all] [--dry-run]

Generate platform packaging icons from public/assets/icons/app-icon.png.

Options:
  --platform   Target platform icon to generate. Defaults to all
  --dry-run    Print commands without writing files
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

function readPngDimensions(filePath) {
  const buffer = readFileSync(filePath);
  const signature = buffer.subarray(0, 8).toString("hex");
  if (signature !== "89504e470d0a1a0a") {
    throw new Error(`Icon source is not a PNG file: ${filePath}`);
  }
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  return { width, height };
}

function ensureSourceIconIsUsable() {
  const { width, height } = readPngDimensions(sourceIconPath);
  if (width !== height) {
    throw new Error(`app-icon.png must be square, got ${width}x${height}`);
  }
  if (width < 1024) {
    console.warn(`Warning: app-icon.png is ${width}x${height}. 1024x1024 or larger is recommended for packaging.`);
  }
}

function ensureOutputRoot() {
  if (!dryRun) {
    mkdirSync(outputRoot, { recursive: true });
  }
}

function buildMacIcons() {
  if (process.platform !== "darwin") {
    throw new Error("macOS icon generation requires running on macOS because it uses sips and iconutil.");
  }

  const iconSizes = [
    [16, "icon_16x16.png"],
    [32, "icon_16x16@2x.png"],
    [32, "icon_32x32.png"],
    [64, "icon_32x32@2x.png"],
    [128, "icon_128x128.png"],
    [256, "icon_128x128@2x.png"],
    [256, "icon_256x256.png"],
    [512, "icon_256x256@2x.png"],
    [512, "icon_512x512.png"],
    [1024, "icon_512x512@2x.png"]
  ];

  if (!dryRun) {
    rmSync(macIconsetDir, { recursive: true, force: true });
    rmSync(macIconPath, { force: true });
    mkdirSync(macIconsetDir, { recursive: true });
  }

  for (const [size, filename] of iconSizes) {
    run("sips", ["-z", String(size), String(size), sourceIconPath, "--out", path.join(macIconsetDir, filename)]);
  }

  run("iconutil", ["-c", "icns", macIconsetDir, "-o", macIconPath]);
}

async function buildWindowsIcon() {
  console.log(`> png-to-ico ${sourceIconPath} -> ${winIconPath}`);
  if (dryRun) {
    return;
  }

  rmSync(winIconPath, { force: true });
  const iconBuffer = await pngToIco(sourceIconPath);
  writeFileSync(winIconPath, iconBuffer);
}

async function main() {
  if (help) {
    printUsage();
    process.exit(0);
  }

  const defaultPlatform =
    process.platform === "darwin" ? "all" : process.platform === "win32" ? "win" : "all";
  const targetPlatform = getOption("platform") ?? defaultPlatform;
  if (!["mac", "win", "all"].includes(targetPlatform)) {
    throw new Error(`Unsupported icon target: ${targetPlatform}`);
  }

  ensureSourceIconIsUsable();
  ensureOutputRoot();

  if (targetPlatform === "mac" || targetPlatform === "all") {
    buildMacIcons();
  }
  if (targetPlatform === "win" || targetPlatform === "all") {
    await buildWindowsIcon();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
