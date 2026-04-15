import { contextBridge, ipcRenderer } from "electron";

type AppConfig = {
  downloadOutputDirectory: string;
  backendUrl: string;
  douyinCookie?: string;
  kuaishouCookie?: string;
};

type BackendStartupState = {
  phase: "idle" | "checking" | "cleaning" | "starting" | "waiting" | "waiting_external" | "online" | "offline" | "error";
  label: string;
  detail: string;
  progress: number;
  managed: boolean;
  updatedAt: string;
};

const api = {
  pickDirectory: () => ipcRenderer.invoke("dialog:pick-directory") as Promise<string | null>,
  pickVideoFile: () => ipcRenderer.invoke("dialog:pick-video") as Promise<string | null>,
  getAppConfig: () => ipcRenderer.invoke("config:get") as Promise<AppConfig>,
  getBackendStartupState: () => ipcRenderer.invoke("backend:start-state:get") as Promise<BackendStartupState>,
  setAppConfig: (config: AppConfig) => ipcRenderer.invoke("config:set", config) as Promise<AppConfig>,
  readClipboardText: () => ipcRenderer.invoke("clipboard:read-text") as Promise<string>,
  openFolder: (targetPath: string) => ipcRenderer.invoke("shell:open-folder", targetPath) as Promise<void>,
  subscribeBackendStartup: (onStateChange: (state: BackendStartupState) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, state: BackendStartupState) => onStateChange(state);
    ipcRenderer.on("backend:startup-state", listener);
    return () => ipcRenderer.removeListener("backend:startup-state", listener);
  },
  subscribeTaskEvents: (url: string, onMessage: (payload: string) => void, onError?: () => void) => {
    const source = new EventSource(url);
    source.onmessage = (event) => onMessage(event.data);
    source.onerror = () => onError?.();
    return () => {
      source.onerror = null;
      source.close();
    };
  }
};

contextBridge.exposeInMainWorld("cliplab", api);
