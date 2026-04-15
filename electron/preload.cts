import { contextBridge, ipcRenderer } from "electron";

type AppConfig = {
  downloadOutputDirectory: string;
  backendUrl: string;
  douyinCookie?: string;
  kuaishouCookie?: string;
};

const api = {
  pickDirectory: () => ipcRenderer.invoke("dialog:pick-directory") as Promise<string | null>,
  pickVideoFile: () => ipcRenderer.invoke("dialog:pick-video") as Promise<string | null>,
  getAppConfig: () => ipcRenderer.invoke("config:get") as Promise<AppConfig>,
  setAppConfig: (config: AppConfig) => ipcRenderer.invoke("config:set", config) as Promise<AppConfig>,
  readClipboardText: () => ipcRenderer.invoke("clipboard:read-text") as Promise<string>,
  openFolder: (targetPath: string) => ipcRenderer.invoke("shell:open-folder", targetPath) as Promise<void>,
  subscribeTaskEvents: (url: string, onMessage: (payload: string) => void) => {
    const source = new EventSource(url);
    source.onmessage = (event) => onMessage(event.data);
    return () => source.close();
  }
};

contextBridge.exposeInMainWorld("cliplab", api);
