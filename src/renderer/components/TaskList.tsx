import type { TaskRecord } from "../../shared/types";

interface TaskListProps {
  tasks: TaskRecord[];
  onOpenFolder: (outputPath: string) => void;
}

export function TaskList({ tasks, onOpenFolder }: TaskListProps) {
  if (tasks.length === 0) {
    return <div className="empty-state">还没有任务，先去解析链接或创建去水印任务。</div>;
  }

  const statusLabelMap: Record<TaskRecord["status"], string> = {
    queued: "排队中",
    running: "处理中",
    succeeded: "已完成",
    failed: "失败",
    canceled: "已取消",
    interrupted: "已中断"
  };

  return (
    <div className="task-list">
      {tasks.map((task) => (
        <article key={task.id} className="task-card">
          <header className="task-card-header">
            <span className="task-kind">{task.type === "download" ? "下载任务" : "去水印任务"}</span>
            <span className={`task-status ${task.status}`}>{statusLabelMap[task.status]}</span>
          </header>
          <div className="task-input-block">
            <p className="task-input-text">{task.input}</p>
          </div>
          <div className="progress-row">
            <div className="progress-bar">
              <span style={{ width: `${task.progress}%` }} />
            </div>
            <strong>{task.progress}%</strong>
          </div>
          <div className="task-meta-list">
            <div className="task-meta-row">
              <span className="task-meta-label">输出</span>
              <span className="task-meta-value">{task.outputPath || "处理中"}</span>
            </div>
            <div className="task-meta-row">
              <span className="task-meta-label">状态</span>
              <span className="task-meta-value">{task.errorMessage || (task.status === "succeeded" ? "任务已完成" : "任务正常运行")}</span>
            </div>
          </div>
          {task.status === "succeeded" && task.outputPath ? (
            <div className="task-card-actions">
              <button
                className="secondary-button small-button"
                onClick={() => onOpenFolder(task.outputPath!)}
                type="button"
              >
                打开文件夹
              </button>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
