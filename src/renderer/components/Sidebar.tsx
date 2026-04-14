interface SidebarProps {
  current: string;
  onSelect: (view: string) => void;
}

const items = [
  { id: "download", label: "链接下载" },
  { id: "watermark", label: "去水印" },
  { id: "tasks", label: "任务列表" },
  { id: "settings", label: "设置" }
];

export function Sidebar({ current, onSelect }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div>
        <div className="brand">
          <div className="brand-mark">C</div>
          <div>
            <h1>ClipLab</h1>
            <p>本地优先视频工具</p>
          </div>
        </div>
        <nav className="nav">
          {items.map((item) => (
            <button
              key={item.id}
              className={item.id === current ? "nav-item active" : "nav-item"}
              onClick={() => onSelect(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="sidebar-footer">
        <span>MVP</span>
        <small>macOS first, Windows ready</small>
      </div>
    </aside>
  );
}
