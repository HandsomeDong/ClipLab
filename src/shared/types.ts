export type TaskType = "download" | "remove_watermark";
export type TaskStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "interrupted";

export interface AppConfig {
  downloadOutputDirectory: string;
  backendUrl: string;
  douyinCookie?: string;
  kuaishouCookie?: string;
}

export interface MediaSource {
  platform: string;
  shareUrl: string;
  resolvedId: string;
  title: string;
  author: string;
  duration: number;
  coverUrl?: string | null;
  downloadUrl?: string | null;
}

export interface ResolveLinkResponse {
  type: "single" | "batch";
  media: MediaSource | null;
  mediaList: MediaSource[];
  userId: string | null;
  userName: string | null;
  fanCount: number;
  photoCount: number;
}

export interface BatchTaskError {
  input: string;
  error: string;
}

export interface BatchDownloadResponse {
  tasks: TaskRecord[];
  failed: BatchTaskError[];
}

export interface ClearHistoryResponse {
  clearedTasks: number;
  clearedLogs: number;
}

export interface WatermarkRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ModelPackage {
  id: string;
  version: string;
  size: number;
  installed: boolean;
  downloadStatus: "idle" | "downloading" | "failed" | "ready";
  checksum?: string | null;
  description: string;
}

export interface TaskRecord {
  id: string;
  type: TaskType;
  status: TaskStatus;
  progress: number;
  input: string;
  outputPath?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
}

export interface LogRecord {
  id: string;
  level: "info" | "warning" | "error";
  source: "desktop" | "api" | "task" | "remote_web";
  message: string;
  createdAt: string;
  taskId?: string | null;
  context: Record<string, unknown>;
}

export interface ServerInfo {
  appName: string;
  localApiUrl: string;
  remoteSubmitUrls: string[];
  remoteWebUrls: string[];
}

declare global {
  interface Window {
    cliplab: {
      pickDirectory: () => Promise<string | null>;
      pickVideoFile: () => Promise<string | null>;
      getAppConfig: () => Promise<AppConfig>;
      setAppConfig: (config: AppConfig) => Promise<AppConfig>;
      readClipboardText: () => Promise<string>;
      openFolder: (path: string) => Promise<void>;
      subscribeTaskEvents: (url: string, onMessage: (payload: string) => void) => () => void;
    };
  }
}
