import type { TaskRecord } from "../../shared/types";

interface TaskListProps {
  tasks: TaskRecord[];
}

export function TaskList({ tasks }: TaskListProps) {
  if (tasks.length === 0) {
    return <div className="empty-state">还没有任务，先去解析链接或创建去水印任务。</div>;
  }

  return (
    <div className="task-list">
      {tasks.map((task) => (
        <article key={task.id} className="task-card">
          <header>
            <div>
              <h3>{task.type === "download" ? "下载任务" : "去水印任务"}</h3>
              <p>{task.input}</p>
            </div>
            <span className={`task-status ${task.status}`}>{task.status}</span>
          </header>
          <div className="progress-row">
            <div className="progress-bar">
              <span style={{ width: `${task.progress}%` }} />
            </div>
            <strong>{task.progress}%</strong>
          </div>
          <footer>
            <span>输出：{task.outputPath || "处理中"}</span>
            <span>{task.errorMessage || "任务正常运行"}</span>
          </footer>
        </article>
      ))}
    </div>
  );
}
