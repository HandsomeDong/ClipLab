import type { LogRecord } from "../../shared/types";

interface LogPanelProps {
  logs: LogRecord[];
}

export function LogPanel({ logs }: LogPanelProps) {
  if (logs.length === 0) {
    return <div className="empty-state">还没有日志，提交任务后这里会显示处理记录。</div>;
  }

  const sourceLabelMap: Record<LogRecord["source"], string> = {
    desktop: "桌面端",
    api: "API",
    task: "任务",
    remote_web: "内网页"
  };

  return (
    <div className="log-list">
      {logs.map((log) => (
        <article key={log.id} className={`log-card ${log.level}`}>
          <header className="log-card-header">
            <strong>{sourceLabelMap[log.source]}</strong>
            <span>{new Date(log.createdAt).toLocaleString()}</span>
          </header>
          <p className="log-message">{log.message}</p>
          {log.taskId ? <small className="log-task-id">任务 ID: {log.taskId}</small> : null}
        </article>
      ))}
    </div>
  );
}
