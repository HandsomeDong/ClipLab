import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { LogPanel } from "./components/LogPanel";
import { Sidebar } from "./components/Sidebar";
import { TaskList } from "./components/TaskList";
import { useTaskEvents } from "./hooks/useTaskEvents";
import type {
  AppConfig,
  BackendStartupState,
  BatchDownloadResponse,
  ClearHistoryResponse,
  LogRecord,
  ModelPackage,
  ServerInfo,
  TaskRecord,
  WatermarkRegion
} from "../shared/types";

type View = "download" | "watermark" | "tasks" | "settings";

const emptyConfig: AppConfig = {
  downloadOutputDirectory: "",
  backendUrl: "http://127.0.0.1:8765",
  douyinCookie: "",
  kuaishouCookie: ""
};

const emptyBackendStartupState: BackendStartupState = {
  phase: "checking",
  label: "检测后端状态",
  detail: "正在读取后端启动状态。",
  progress: 5,
  managed: false,
  updatedAt: ""
};

function toSafeFileUrl(filePath: string) {
  if (!filePath) {
    return "";
  }

  try {
    const normalized = filePath.replace(/\\/g, "/");
    const encodedPath = normalized
      .split("/")
      .map((segment, index) => {
        if (segment === "") {
          return index === 0 ? "" : segment;
        }
        return encodeURIComponent(segment);
      })
      .join("/")
      .replace(/^([A-Za-z])%3A/i, "$1:");

    if (normalized.startsWith("/")) {
      return `file://${encodedPath}`;
    }

    return `file:///${encodedPath}`;
  } catch {
    return `file://${filePath.replace(/#/g, "%23").replace(/\?/g, "%3F")}`;
  }
}

async function fetchJson<T>(url: string, init?: RequestInit) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json"
    },
    ...init
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed with ${response.status}`;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      message = parsed.detail || message;
    } catch {
      // Fall back to raw response text.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function sortTasks(tasks: TaskRecord[]) {
  return [...tasks].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

export default function App() {
  const [view, setView] = useState<View>("download");
  const [config, setConfig] = useState<AppConfig>(emptyConfig);
  const [backendReachable, setBackendReachable] = useState(false);
  const [backendStartup, setBackendStartup] = useState<BackendStartupState>(emptyBackendStartupState);
  const [shareInputs, setShareInputs] = useState<string[]>([""]);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [clearHistoryLoading, setClearHistoryLoading] = useState(false);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [models, setModels] = useState<ModelPackage[]>([]);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const [watermarkVideoPath, setWatermarkVideoPath] = useState("");
  const [watermarkOutputDirectory, setWatermarkOutputDirectory] = useState("");
  const [region, setRegion] = useState<WatermarkRegion | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftRect, setDraftRect] = useState<WatermarkRegion | null>(null);
  const [notice, setNotice] = useState("ClipLab 已准备好。");
  const [videoDuration, setVideoDuration] = useState(0);
  const [videoCurrentTime, setVideoCurrentTime] = useState(0);
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const videoStageRef = useRef<HTMLDivElement | null>(null);
  const [videoDisplayRect, setVideoDisplayRect] = useState<{ width: number; height: number } | null>(null);

  const backendUrl = config.backendUrl || emptyConfig.backendUrl;
  const backendOnline = backendReachable || backendStartup.phase === "online";
  const backendStarting =
    !backendOnline &&
    (backendStartup.phase === "checking" ||
      backendStartup.phase === "cleaning" ||
      backendStartup.phase === "starting" ||
      backendStartup.phase === "waiting" ||
      backendStartup.phase === "waiting_external");
  const backendStatusClassName = backendOnline
    ? "pill online"
    : backendStartup.phase === "error"
      ? "pill error"
      : backendStarting
        ? "pill starting"
        : "pill offline";
  const backendStatusText = backendOnline
    ? "后端在线"
    : backendStartup.phase === "error"
      ? "后端异常"
      : backendStarting
        ? "后端启动中"
        : backendStartup.phase === "waiting_external"
          ? "等待后端"
          : "后端离线";
  const showBackendStartupCard = !backendOnline && backendStartup.phase !== "idle";

  const refreshTasks = useCallback(async () => {
    if (!backendUrl) {
      return;
    }
    try {
      const data = await fetchJson<TaskRecord[]>(`${backendUrl}/api/tasks`);
      setTasks(sortTasks(data));
      setBackendReachable(true);
    } catch {
      setBackendReachable(false);
    }
  }, [backendUrl]);

  const refreshModels = useCallback(async () => {
    if (!backendUrl) {
      return;
    }
    try {
      const data = await fetchJson<ModelPackage[]>(`${backendUrl}/api/models`);
      setModels(data);
    } catch {
      setNotice("模型状态读取失败，请确认后端已启动。");
    }
  }, [backendUrl]);

  const refreshLogs = useCallback(async () => {
    if (!backendUrl) {
      return;
    }
    try {
      const data = await fetchJson<LogRecord[]>(`${backendUrl}/api/logs`);
      setLogs(data);
    } catch {
      setNotice("日志读取失败，请确认后端已启动。");
    }
  }, [backendUrl]);

  const refreshServerInfo = useCallback(async () => {
    if (!backendUrl) {
      return;
    }
    try {
      const data = await fetchJson<ServerInfo>(`${backendUrl}/api/server-info`);
      setServerInfo(data);
    } catch {
      setNotice("服务地址读取失败，请确认后端已启动。");
    }
  }, [backendUrl]);

  useTaskEvents(
    backendUrl,
    useCallback((task: TaskRecord) => {
      setTasks((current) => {
        const next = current.filter((item) => item.id !== task.id);
        next.push(task);
        return sortTasks(next);
      });
    }, []),
    useCallback((log: LogRecord) => {
      setLogs((current) => [log, ...current].slice(0, 40));
    }, []),
    useCallback((online: boolean) => {
      setBackendReachable(online);
    }, [])
  );

  useEffect(() => {
    window.cliplab.getAppConfig().then((storedConfig) => {
      setConfig(storedConfig);
    });
  }, []);

  useEffect(() => {
    let disposed = false;

    window.cliplab.getBackendStartupState().then((state) => {
      if (!disposed) {
        setBackendStartup(state);
      }
    });

    const unsubscribe = window.cliplab.subscribeBackendStartup((state) => {
      if (!disposed) {
        setBackendStartup(state);
      }
    });

    return () => {
      disposed = true;
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    refreshTasks();
    refreshModels();
    refreshLogs();
    refreshServerInfo();
  }, [refreshLogs, refreshModels, refreshServerInfo, refreshTasks]);

  useEffect(() => {
    if (!backendOnline) {
      return;
    }

    void refreshModels();
    void refreshServerInfo();
  }, [backendOnline, refreshModels, refreshServerInfo]);

  const updateShareInput = (index: number, value: string) => {
    setShareInputs((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const addShareInput = () => {
    setShareInputs((current) => [...current, ""]);
  };

  const removeShareInput = (index: number) => {
    setShareInputs((current) => (current.length === 1 ? current : current.filter((_, itemIndex) => itemIndex !== index)));
  };

  const onPasteInput = async (index: number) => {
    try {
      const text = await window.cliplab.readClipboardText();
      if (!text.trim()) {
        setNotice("剪贴板里没有可用内容。");
        return;
      }
      updateShareInput(index, text);
      setNotice("已从剪贴板填入内容。");
    } catch (error) {
      setNotice((error as Error).message);
    }
  };

  const onPickDownloadOutputDir = async () => {
    const picked = await window.cliplab.pickDirectory();
    if (!picked) {
      return "";
    }
    const nextConfig = { ...config, downloadOutputDirectory: picked };
    const saved = await window.cliplab.setAppConfig(nextConfig);
    setConfig(saved);
    setNotice(`下载输出目录已更新到 ${picked}`);
    return picked;
  };

  const ensureDownloadOutputDirectory = async () => {
    if (config.downloadOutputDirectory.trim()) {
      return config.downloadOutputDirectory.trim();
    }
    setNotice("链接下载必须先选择输出目录。");
    return await onPickDownloadOutputDir();
  };

  const onDownloadAll = async () => {
    const nonEmptyInputs = shareInputs.map((item) => item.trim()).filter(Boolean);
    if (nonEmptyInputs.length === 0) {
      setNotice("请先输入至少一个分享文案或链接。");
      return;
    }

    const outputDirectory = await ensureDownloadOutputDirectory();
    if (!outputDirectory) {
      return;
    }

    setDownloadLoading(true);
    try {
      const response = await fetchJson<BatchDownloadResponse>(`${backendUrl}/api/tasks/download/batch`, {
        method: "POST",
        body: JSON.stringify({
          shareUrls: nonEmptyInputs,
          outputDirectory,
          douyinCookie: config.douyinCookie || "",
          kuaishouCookie: config.kuaishouCookie || ""
        })
      });
      if (response.tasks.length > 0) {
        setTasks((current) => sortTasks([...current, ...response.tasks]));
        setView("tasks");
      }
      const skippedCount = shareInputs.length - nonEmptyInputs.length;
      setNotice(
        `已创建 ${response.tasks.length} 个下载任务，失败 ${response.failed.length} 个，跳过空输入 ${skippedCount} 个。`
      );
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setDownloadLoading(false);
    }
  };

  const onSaveConfig = async () => {
    const saved = await window.cliplab.setAppConfig(config);
    setConfig(saved);
    setNotice("下载设置已保存。");
  };

  const onPickVideo = async () => {
    const picked = await window.cliplab.pickVideoFile();
    if (!picked) {
      return;
    }
    setWatermarkVideoPath(picked);
    setRegion(null);
    setDraftRect(null);
    setVideoCurrentTime(0);
    setVideoDuration(0);
    setIsVideoPlaying(false);
  };

  const onPickWatermarkOutputDir = async () => {
    const picked = await window.cliplab.pickDirectory();
    if (!picked) {
      return;
    }
    setWatermarkOutputDirectory(picked);
    setNotice(`去水印输出目录已设置到 ${picked}`);
  };

  const onOpenFolder = async (targetPath: string) => {
    try {
      await window.cliplab.openFolder(targetPath);
    } catch (error) {
      setNotice((error as Error).message);
    }
  };

  const onCreateWatermarkTask = async () => {
    if (!watermarkVideoPath || !region) {
      setNotice("请先选择视频并框选去水印区域。");
      return;
    }
    try {
      const task = await fetchJson<TaskRecord>(`${backendUrl}/api/tasks/remove-watermark`, {
        method: "POST",
        body: JSON.stringify({
          inputPath: watermarkVideoPath,
          outputDirectory: watermarkOutputDirectory,
          region,
          algorithm: "sttn_auto"
        })
      });
      setTasks((current) => {
        const next = current.filter((item) => item.id !== task.id);
        next.push(task);
        return sortTasks(next);
      });
      setView("tasks");
      setNotice("去水印任务已创建。");
      refreshTasks();
    } catch (error) {
      setNotice((error as Error).message);
    }
  };

  const onClearHistory = async () => {
    setClearHistoryLoading(true);
    try {
      const response = await fetchJson<ClearHistoryResponse>(`${backendUrl}/api/history/clear`, {
        method: "POST"
      });
      await Promise.all([refreshTasks(), refreshLogs()]);
      setNotice(`已清除 ${response.clearedTasks} 条历史任务，清空 ${response.clearedLogs} 条日志。`);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setClearHistoryLoading(false);
    }
  };

  const onDownloadModel = async (modelId: string) => {
    try {
      await fetchJson(`${backendUrl}/api/models/download`, {
        method: "POST",
        body: JSON.stringify({ modelId })
      });
      setNotice(`${modelId} 下载任务已开始。`);
      refreshModels();
    } catch (error) {
      setNotice((error as Error).message);
    }
  };

  const onOverlayPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    videoRef.current?.pause();
    setIsVideoPlaying(false);
    event.currentTarget.setPointerCapture(event.pointerId);
    const rect = event.currentTarget.getBoundingClientRect();
    const startX = (event.clientX - rect.left) / rect.width;
    const startY = (event.clientY - rect.top) / rect.height;
    setDragStart({ x: startX, y: startY });
    setDraftRect({ x: startX, y: startY, width: 0, height: 0 });
  };

  const onOverlayPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const currentX = (event.clientX - rect.left) / rect.width;
    const currentY = (event.clientY - rect.top) / rect.height;
    setDraftRect({
      x: Math.min(dragStart.x, currentX),
      y: Math.min(dragStart.y, currentY),
      width: Math.abs(currentX - dragStart.x),
      height: Math.abs(currentY - dragStart.y)
    });
  };

  const onOverlayPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (draftRect && draftRect.width > 0.01 && draftRect.height > 0.01) {
      setRegion(draftRect);
    }
    setDragStart(null);
  };

  const toggleVideoPlayback = async () => {
    if (!videoRef.current) {
      return;
    }
    if (videoRef.current.paused) {
      await videoRef.current.play();
      setIsVideoPlaying(true);
    } else {
      videoRef.current.pause();
      setIsVideoPlaying(false);
    }
  };

  const seekVideo = (seconds: number) => {
    if (!videoRef.current) {
      return;
    }
    const nextTime = Math.max(0, Math.min(videoDuration || 0, videoRef.current.currentTime + seconds));
    videoRef.current.currentTime = nextTime;
    setVideoCurrentTime(nextTime);
  };

  const onTimelineChange = (value: number) => {
    if (!videoRef.current) {
      return;
    }
    videoRef.current.currentTime = value;
    setVideoCurrentTime(value);
  };

  const updateVideoDisplayRect = useCallback(() => {
    const stage = videoStageRef.current;
    const video = videoRef.current;
    if (!stage || !video) {
      setVideoDisplayRect(null);
      return;
    }

    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    if (!sourceWidth || !sourceHeight) {
      setVideoDisplayRect(null);
      return;
    }

    const stageWidth = stage.clientWidth;
    const stageHeight = stage.clientHeight;
    if (!stageWidth || !stageHeight) {
      setVideoDisplayRect(null);
      return;
    }

    const scale = Math.min(stageWidth / sourceWidth, stageHeight / sourceHeight);
    setVideoDisplayRect({
      width: Math.max(1, Math.floor(sourceWidth * scale)),
      height: Math.max(1, Math.floor(sourceHeight * scale))
    });
  }, []);

  useEffect(() => {
    const handleResize = () => updateVideoDisplayRect();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [updateVideoDisplayRect]);

  useEffect(() => {
    const stage = videoStageRef.current;
    if (!stage) {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      updateVideoDisplayRect();
    });
    resizeObserver.observe(stage);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateVideoDisplayRect, watermarkVideoPath, view]);

  useEffect(() => {
    updateVideoDisplayRect();
  }, [updateVideoDisplayRect, watermarkVideoPath, view]);

  const taskCountLabel = useMemo(() => {
    const activeCount = tasks.filter((task) => task.status === "running" || task.status === "queued").length;
    return `${activeCount} 个任务`;
  }, [tasks]);

  const latestWatermarkTask = useMemo(
    () => tasks.find((task) => task.type === "remove_watermark" && task.status === "succeeded" && !!task.outputPath),
    [tasks]
  );
  const watermarkVideoUrl = useMemo(() => toSafeFileUrl(watermarkVideoPath), [watermarkVideoPath]);

  return (
    <div className="app-shell">
      <Sidebar
        current={view}
        onSelect={(next) => setView(next as View)}
        backendStartup={backendStartup}
        showBackendStartup={showBackendStartupCard}
      />
      <main className="content">
        <header className="topbar">
          <div>
            <h2>{view === "download" ? "链接下载" : view === "watermark" ? "去水印" : view === "tasks" ? "任务列表" : "设置"}</h2>
            <p>{notice}</p>
          </div>
          <div className="topbar-side">
            <div className="status-pills">
              <span className={backendStatusClassName}>{backendStatusText}</span>
              <span className="pill neutral">{taskCountLabel}</span>
            </div>
          </div>
        </header>

        {view === "download" && (
          <section className="panel-grid">
            <article className="panel">
              <h3>批量下载</h3>
              <p>支持整段分享文案里的抖音、快手单视频链接。下载前必须先选择输出目录。</p>
              <div className="download-input-list">
                {shareInputs.map((value, index) => (
                  <div key={`share-input-${index}`} className="download-input-card">
                    <div className="section-header compact">
                      <strong>链接 {index + 1}</strong>
                      <div className="button-row compact">
                        <button className="secondary-button small-button" onClick={() => onPasteInput(index)} type="button">
                          粘贴
                        </button>
                        <button
                          className="secondary-button small-button"
                          disabled={shareInputs.length === 1}
                          onClick={() => removeShareInput(index)}
                          type="button"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                    <textarea
                      className="textarea compact"
                      value={value}
                      onChange={(event) => updateShareInput(index, event.target.value)}
                      placeholder="粘贴分享文案或视频链接"
                    />
                  </div>
                ))}
              </div>
              <div className="button-row">
                <button className="primary-button" disabled={downloadLoading} onClick={onDownloadAll} type="button">
                  {downloadLoading ? "提交中..." : "下载"}
                </button>
                <button className="secondary-button" onClick={addShareInput} type="button">
                  添加
                </button>
                <button className="secondary-button" onClick={onPickDownloadOutputDir} type="button">
                  选择输出目录
                </button>
                <button
                  className="secondary-button"
                  disabled={!config.downloadOutputDirectory}
                  onClick={() => onOpenFolder(config.downloadOutputDirectory)}
                  type="button"
                >
                  打开输出文件夹
                </button>
              </div>
              <small>当前下载目录：{config.downloadOutputDirectory || "未设置，提交前必须选择"}</small>
            </article>

            <article className="panel">
              <h3>下载说明</h3>
              <div className="media-card info-list">
                <span>输入内容可以是一整段分享文案，程序会自动提取里面的真实链接。</span>
                <span>文件名会优先使用作品标题；标题超过 10 个汉字时会自动截断。</span>
                <span>如果某个平台后续触发风控，可在设置页填写对应 Cookie 作为兜底。</span>
                <span>任务提交后会自动切到任务列表，你可以在那里查看实时进度和失败原因。</span>
              </div>
            </article>
          </section>
        )}

        {view === "watermark" && (
          <section className="panel-grid watermark-layout">
            <article className="panel watermark-sidebar-panel">
              <h3>选择视频</h3>
              <p>先选一个本地视频，再在预览区拖出水印框。输出目录可留空，留空时默认输出到原视频目录。</p>
              <div className="button-row">
                <button className="primary-button" onClick={onPickVideo} type="button">
                  选择本地视频
                </button>
                <button className="secondary-button" onClick={onPickWatermarkOutputDir} type="button">
                  选择输出目录
                </button>
                <button
                  className="secondary-button"
                  disabled={!watermarkOutputDirectory}
                  onClick={() => setWatermarkOutputDirectory("")}
                  type="button"
                >
                  使用原目录
                </button>
              </div>
              <small>{watermarkVideoPath || "还未选择视频"}</small>
              <small>当前去水印目录：{watermarkOutputDirectory || "未选择，默认使用原视频目录"}</small>
              <div className="region-summary">
                <strong>当前区域</strong>
                <span className="region-text">{region ? JSON.stringify(region) : "尚未框选"}</span>
              </div>
              <small>输出文件会自动追加 `_no_watermark` 后缀。</small>
              <div className="watermark-actions">
                <button className="primary-button" disabled={!region || !watermarkVideoPath} onClick={onCreateWatermarkTask} type="button">
                  创建去水印任务
                </button>
                {latestWatermarkTask?.outputPath ? (
                  <button
                    className="secondary-button"
                    onClick={() => onOpenFolder(latestWatermarkTask.outputPath!)}
                    type="button"
                  >
                    打开文件夹
                  </button>
                ) : null}
              </div>
            </article>

            <article className="panel watermark-preview-panel">
              <h3>手动框选</h3>
              <div className="video-stage" ref={videoStageRef}>
                {watermarkVideoPath ? (
                  <div
                    className="video-frame"
                    style={
                      videoDisplayRect
                        ? {
                            width: `${videoDisplayRect.width}px`,
                            height: `${videoDisplayRect.height}px`
                          }
                        : undefined
                    }
                  >
                    <video
                      key={watermarkVideoPath}
                      ref={videoRef}
                      src={watermarkVideoUrl}
                      className="video-preview"
                      preload="metadata"
                      onLoadedMetadata={(event) => {
                        setVideoDuration(event.currentTarget.duration || 0);
                        setVideoCurrentTime(event.currentTarget.currentTime || 0);
                        updateVideoDisplayRect();
                      }}
                      onTimeUpdate={(event) => {
                        setVideoCurrentTime(event.currentTarget.currentTime || 0);
                      }}
                      onPlay={() => setIsVideoPlaying(true)}
                      onPause={() => setIsVideoPlaying(false)}
                      onError={() => {
                        setIsVideoPlaying(false);
                        setVideoDisplayRect(null);
                        setNotice("视频预览加载失败，请检查文件路径或格式是否受支持。");
                      }}
                    />
                    <div
                      className="selection-surface"
                      onPointerDown={onOverlayPointerDown}
                      onPointerMove={onOverlayPointerMove}
                      onPointerUp={onOverlayPointerUp}
                      onPointerCancel={onOverlayPointerUp}
                    >
                      {(draftRect || region) && (
                        <div
                          className="selection-rect"
                          style={{
                            left: `${(draftRect || region)!.x * 100}%`,
                            top: `${(draftRect || region)!.y * 100}%`,
                            width: `${(draftRect || region)!.width * 100}%`,
                            height: `${(draftRect || region)!.height * 100}%`
                          }}
                        />
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="empty-stage">选择视频后，在这里直接框选去水印区域。</div>
                )}
              </div>
              {watermarkVideoPath && (
                <div className="video-controls">
                  <div className="button-row">
                    <button className="secondary-button" onClick={() => seekVideo(-2)} type="button">
                      后退 2 秒
                    </button>
                    <button className="primary-button" onClick={toggleVideoPlayback} type="button">
                      {isVideoPlaying ? "暂停预览" : "播放预览"}
                    </button>
                    <button className="secondary-button" onClick={() => seekVideo(2)} type="button">
                      前进 2 秒
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => {
                        setRegion(null);
                        setDraftRect(null);
                      }}
                      type="button"
                    >
                      清除框选
                    </button>
                  </div>
                  <div className="timeline-row">
                    <span>{videoCurrentTime.toFixed(1)}s</span>
                    <input
                      type="range"
                      min={0}
                      max={videoDuration || 0}
                      step={0.1}
                      value={Math.min(videoCurrentTime, videoDuration || 0)}
                      onChange={(event) => onTimelineChange(Number(event.target.value))}
                    />
                    <span>{videoDuration.toFixed(1)}s</span>
                  </div>
                </div>
              )}
            </article>
          </section>
        )}

        {view === "tasks" && (
          <section className="panel-grid task-page-grid">
            <article className="panel panel-scroll">
              <div className="section-header">
                <div>
                  <h3>任务中心</h3>
                  <p>下载和去水印任务统一在这里追踪。</p>
                </div>
                <div className="button-row compact">
                  <button className="secondary-button small-button" onClick={refreshTasks} type="button">
                    刷新
                  </button>
                  <button className="secondary-button small-button" disabled={clearHistoryLoading} onClick={onClearHistory} type="button">
                    {clearHistoryLoading ? "清理中..." : "清除记录"}
                  </button>
                </div>
              </div>
              <TaskList tasks={tasks} onOpenFolder={onOpenFolder} />
            </article>
            <article className="panel panel-scroll">
              <div className="section-header">
                <div>
                  <h3>运行日志</h3>
                  <p>手机端和桌面端提交的任务都会记录在这里。</p>
                </div>
                <button className="secondary-button small-button" onClick={refreshLogs} type="button">
                  刷新
                </button>
              </div>
              <LogPanel logs={logs} />
            </article>
          </section>
        )}

        {view === "settings" && (
          <section className="panel-grid settings-page-grid">
            <article className="panel">
              <h3>应用设置</h3>
              <div className="setting-row">
                <span>后端地址</span>
                <code>{config.backendUrl}</code>
              </div>
              <div className="setting-row">
                <span>下载输出目录</span>
                <code>{config.downloadOutputDirectory || "未设置"}</code>
              </div>
              <button className="secondary-button" onClick={onPickDownloadOutputDir} type="button">
                修改下载目录
              </button>
              <div className="setting-form">
                <label className="field-label" htmlFor="douyin-cookie">
                  抖音 Cookie（可选）
                </label>
                <textarea
                  id="douyin-cookie"
                  className="textarea compact"
                  value={config.douyinCookie || ""}
                  onChange={(event) => setConfig((current) => ({ ...current, douyinCookie: event.target.value }))}
                  placeholder="仅在抖音解析失败或风控时再填写"
                />
                <label className="field-label" htmlFor="kuaishou-cookie">
                  快手 Cookie（可选）
                </label>
                <textarea
                  id="kuaishou-cookie"
                  className="textarea compact"
                  value={config.kuaishouCookie || ""}
                  onChange={(event) => setConfig((current) => ({ ...current, kuaishouCookie: event.target.value }))}
                  placeholder="快手默认无需登录，只有异常时再填写"
                />
                <div className="button-row">
                  <button className="primary-button" onClick={onSaveConfig} type="button">
                    保存下载设置
                  </button>
                </div>
              </div>
            </article>

            <article className="panel panel-scroll settings-model-panel">
              <h3>模型管理</h3>
              <div className="model-list settings-model-list">
                {models.length > 0 ? (
                  models.map((model) => (
                    <div key={model.id} className="model-card">
                      <div>
                        <strong>{model.id}</strong>
                        <p>{model.description}</p>
                      </div>
                      <div className="model-meta">
                        <span>{(model.size / 1024 / 1024).toFixed(1)} MB</span>
                        <span>{model.installed ? "已安装" : model.downloadStatus}</span>
                      </div>
                      <button
                        className="primary-button"
                        disabled={model.installed}
                        onClick={() => onDownloadModel(model.id)}
                        type="button"
                      >
                        {model.installed ? "已就绪" : "下载模型"}
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="empty-state">
                    {backendOnline ? "模型列表暂时还没加载出来，可以点上方刷新或稍等片刻。" : "后端就绪后，这里会自动显示可用模型。"}
                  </div>
                )}
              </div>
            </article>
            <article className="panel">
              <h3>内网提交</h3>
              <div className="model-list">
                <div className="model-card">
                  <div>
                    <strong>手机提交页</strong>
                    <p>确保手机和桌面端在同一内网，打开任一链接即可提交下载任务。</p>
                  </div>
                  <div className="link-list">
                    {(serverInfo?.remoteWebUrls || []).map((url) => (
                      <code key={url}>{url}</code>
                    ))}
                  </div>
                </div>
                <div className="model-card">
                  <div>
                    <strong>HTTP API</strong>
                    <p>你也可以直接在其他设备调用下载接口。</p>
                  </div>
                  <div className="link-list">
                    {(serverInfo?.remoteSubmitUrls || []).map((url) => (
                      <code key={url}>{url}</code>
                    ))}
                  </div>
                </div>
              </div>
            </article>
          </section>
        )}
      </main>
    </div>
  );
}
