import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { LogPanel } from "./components/LogPanel";
import { Sidebar } from "./components/Sidebar";
import { TaskList } from "./components/TaskList";
import { useTaskEvents } from "./hooks/useTaskEvents";
import type {
  AppConfig,
  BatchDownloadResponse,
  LogRecord,
  ModelPackage,
  ServerInfo,
  TaskRecord,
  WatermarkRegion
} from "../shared/types";

type View = "download" | "watermark" | "tasks" | "settings";

const emptyConfig: AppConfig = {
  outputDirectory: "",
  backendUrl: "http://127.0.0.1:8765",
  douyinCookie: "",
  kuaishouCookie: ""
};

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
  const [backendOnline, setBackendOnline] = useState(false);
  const [shareInputs, setShareInputs] = useState<string[]>([""]);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [models, setModels] = useState<ModelPackage[]>([]);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const [watermarkVideoPath, setWatermarkVideoPath] = useState("");
  const [region, setRegion] = useState<WatermarkRegion | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftRect, setDraftRect] = useState<WatermarkRegion | null>(null);
  const [notice, setNotice] = useState("ClipLab 已准备好。");
  const [videoDuration, setVideoDuration] = useState(0);
  const [videoCurrentTime, setVideoCurrentTime] = useState(0);
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const backendUrl = config.backendUrl || emptyConfig.backendUrl;

  const refreshTasks = useCallback(async () => {
    if (!backendUrl) {
      return;
    }
    try {
      const data = await fetchJson<TaskRecord[]>(`${backendUrl}/api/tasks`);
      setTasks(sortTasks(data));
      setBackendOnline(true);
    } catch {
      setBackendOnline(false);
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
      setBackendOnline(online);
    }, [])
  );

  useEffect(() => {
    window.cliplab.getAppConfig().then((storedConfig) => {
      setConfig(storedConfig);
    });
  }, []);

  useEffect(() => {
    refreshTasks();
    refreshModels();
    refreshLogs();
    refreshServerInfo();
  }, [refreshLogs, refreshModels, refreshServerInfo, refreshTasks]);

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

  const onDownloadAll = async () => {
    const nonEmptyInputs = shareInputs.map((item) => item.trim()).filter(Boolean);
    if (nonEmptyInputs.length === 0) {
      setNotice("请先输入至少一个分享文案或链接。");
      return;
    }

    setDownloadLoading(true);
    try {
      const response = await fetchJson<BatchDownloadResponse>(`${backendUrl}/api/tasks/download/batch`, {
        method: "POST",
        body: JSON.stringify({
          shareUrls: nonEmptyInputs,
          outputDirectory: config.outputDirectory || "",
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

  const onPickOutputDir = async () => {
    const picked = await window.cliplab.pickDirectory();
    if (!picked) {
      return;
    }
    const nextConfig = { ...config, outputDirectory: picked };
    const saved = await window.cliplab.setAppConfig(nextConfig);
    setConfig(saved);
    setNotice(`输出目录已更新到 ${picked}`);
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
          outputDirectory: config.outputDirectory,
          region,
          algorithm: "sttn_auto"
        })
      });
      // 直接更新本地状态，确保立即显示
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

  const taskCountLabel = useMemo(() => {
    const activeCount = tasks.filter((t) => t.status === "running" || t.status === "queued").length;
    return `${activeCount} 个任务`;
  }, [tasks]);

  return (
    <div className="app-shell">
      <Sidebar current={view} onSelect={(next) => setView(next as View)} />
      <main className="content">
        <header className="topbar">
          <div>
            <h2>{view === "download" ? "链接下载" : view === "watermark" ? "去水印" : view === "tasks" ? "任务列表" : "设置"}</h2>
            <p>{notice}</p>
          </div>
          <div className="status-pills">
            <span className={backendOnline ? "pill online" : "pill offline"}>
              {backendOnline ? "后端在线" : "后端离线"}
            </span>
            <span className="pill neutral">{taskCountLabel}</span>
          </div>
        </header>

        {view === "download" && (
          <section className="panel-grid">
            <article className="panel">
              <h3>批量下载</h3>
              <p>支持整段分享文案里的抖音、快手单视频链接。默认 1 个输入框，可按需继续添加。</p>
              <div className="download-input-list">
                {shareInputs.map((value, index) => (
                  <div key={`share-input-${index}`} className="download-input-card">
                    <div className="section-header compact">
                      <strong>链接 {index + 1}</strong>
                      <div className="button-row compact">
                        <button className="secondary-button" onClick={() => onPasteInput(index)}>
                          粘贴
                        </button>
                        <button
                          className="secondary-button"
                          disabled={shareInputs.length === 1}
                          onClick={() => removeShareInput(index)}
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
                <button className="primary-button" disabled={downloadLoading} onClick={onDownloadAll}>
                  {downloadLoading ? "提交中..." : "下载"}
                </button>
                <button className="secondary-button" onClick={addShareInput}>
                  添加
                </button>
                <button className="secondary-button" onClick={() => onPasteInput(shareInputs.length - 1)}>
                  粘贴最后一项
                </button>
                <button className="secondary-button" onClick={onPickOutputDir}>
                  选择输出目录
                </button>
              </div>
              <small>当前输出目录：{config.outputDirectory || "未设置"}</small>
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
            <article className="panel">
              <h3>选择视频</h3>
              <p>先选一个本地视频，再在预览区拖出水印框。</p>
              <div className="button-row">
                <button className="primary-button" onClick={onPickVideo}>
                  选择本地视频
                </button>
                <button className="secondary-button" onClick={onPickOutputDir}>
                  选择输出目录
                </button>
              </div>
              <small>{watermarkVideoPath || "还未选择视频"}</small>
              <div className="region-summary">
                <strong>当前区域</strong>
                <span>{region ? JSON.stringify(region) : "尚未框选"}</span>
              </div>
              <small>播放条已移到预览区下方，框选时不会再被原生进度条挡住。</small>
              <button className="primary-button" disabled={!region || !watermarkVideoPath} onClick={onCreateWatermarkTask}>
                创建去水印任务
              </button>
            </article>

            <article className="panel">
              <h3>手动框选</h3>
              <div className="video-stage">
                {watermarkVideoPath ? (
                  <>
                    <video
                      key={watermarkVideoPath}
                      ref={videoRef}
                      src={`file://${watermarkVideoPath}`}
                      className="video-preview"
                      onLoadedMetadata={(event) => {
                        setVideoDuration(event.currentTarget.duration || 0);
                        setVideoCurrentTime(event.currentTarget.currentTime || 0);
                      }}
                      onTimeUpdate={(event) => {
                        setVideoCurrentTime(event.currentTarget.currentTime || 0);
                      }}
                      onPlay={() => setIsVideoPlaying(true)}
                      onPause={() => setIsVideoPlaying(false)}
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
                  </>
                ) : (
                  <div className="empty-stage">选择视频后，在这里直接框选去水印区域。</div>
                )}
              </div>
              {watermarkVideoPath && (
                <div className="video-controls">
                  <div className="button-row">
                    <button className="secondary-button" onClick={() => seekVideo(-2)}>
                      后退 2 秒
                    </button>
                    <button className="primary-button" onClick={toggleVideoPlayback}>
                      {isVideoPlaying ? "暂停预览" : "播放预览"}
                    </button>
                    <button className="secondary-button" onClick={() => seekVideo(2)}>
                      前进 2 秒
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => {
                        setRegion(null);
                        setDraftRect(null);
                      }}
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
          <section className="panel-grid">
            <article className="panel">
              <div className="section-header">
                <div>
                  <h3>任务中心</h3>
                  <p>下载和去水印任务统一在这里追踪。</p>
                </div>
                <button className="secondary-button" onClick={refreshTasks}>
                  刷新
                </button>
              </div>
              <TaskList tasks={tasks} />
            </article>
            <article className="panel">
              <div className="section-header">
                <div>
                  <h3>运行日志</h3>
                  <p>手机端和桌面端提交的任务都会记录在这里。</p>
                </div>
                <button className="secondary-button" onClick={refreshLogs}>
                  刷新
                </button>
              </div>
              <LogPanel logs={logs} />
            </article>
          </section>
        )}

        {view === "settings" && (
          <section className="panel-grid">
            <article className="panel">
              <h3>应用设置</h3>
              <div className="setting-row">
                <span>后端地址</span>
                <code>{config.backendUrl}</code>
              </div>
              <div className="setting-row">
                <span>默认输出目录</span>
                <code>{config.outputDirectory}</code>
              </div>
              <button className="secondary-button" onClick={onPickOutputDir}>
                修改输出目录
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
                  <button className="primary-button" onClick={onSaveConfig}>
                    保存下载设置
                  </button>
                </div>
              </div>
            </article>

            <article className="panel">
              <h3>模型管理</h3>
              <div className="model-list">
                {models.map((model) => (
                  <div key={model.id} className="model-card">
                    <div>
                      <strong>{model.id}</strong>
                      <p>{model.description}</p>
                    </div>
                    <div className="model-meta">
                      <span>{(model.size / 1024 / 1024).toFixed(1)} MB</span>
                      <span>{model.installed ? "已安装" : model.downloadStatus}</span>
                    </div>
                    <button className="primary-button" disabled={model.installed} onClick={() => onDownloadModel(model.id)}>
                      {model.installed ? "已就绪" : "下载模型"}
                    </button>
                  </div>
                ))}
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
