import { useState } from "react";
import type { BackendStartupState } from "../../shared/types";

interface SidebarProps {
  current: string;
  onSelect: (view: string) => void;
  backendStartup: BackendStartupState;
  showBackendStartup: boolean;
}

const BRAND_ICON_SRC = `${window.location.origin}${window.location.pathname.replace(/[^/]*$/, "")}assets/icons/app-icon.png`;

const items = [
  { id: "download", label: "链接下载" },
  { id: "watermark", label: "去水印" },
  { id: "tasks", label: "任务列表" },
  { id: "settings", label: "设置" }
];

export function Sidebar({ current, onSelect, backendStartup, showBackendStartup }: SidebarProps) {
  const [iconFailed, setIconFailed] = useState(false);

  return (
    <aside className="sidebar">
      <div>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            {!iconFailed ? (
              <img
                className="brand-icon"
                src={BRAND_ICON_SRC}
                alt="ClipLab"
                onError={() => setIconFailed(true)}
              />
            ) : (
              <span className="brand-fallback">C</span>
            )}
          </div>
          <div>
            <h1>ClipLab</h1>
            <p>七里翔短视频创作工具</p>
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
      {showBackendStartup ? (
        <div className="sidebar-footer">
          <div className={`backend-startup-card sidebar-startup-card ${backendStartup.phase}`}>
            <div className="backend-startup-header">
              <strong>{backendStartup.label}</strong>
              <span>{Math.round(backendStartup.progress)}%</span>
            </div>
            <div
              className="backend-startup-progress"
              role="progressbar"
              aria-label={backendStartup.label}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={Math.round(backendStartup.progress)}
            >
              <span style={{ width: `${Math.max(0, Math.min(100, backendStartup.progress))}%` }} />
            </div>
            <p>{backendStartup.detail}</p>
          </div>
        </div>
      ) : (
        <div className="sidebar-footer" />
      )}
    </aside>
  );
}
