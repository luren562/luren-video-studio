const PROJECT_STATUS: Record<string, { label: string; cls: string }> = {
  generating: { label: "生成中", cls: "run" },
  spec_ready: { label: "待渲染", cls: "info" },
  pending_review: { label: "待审核", cls: "warn" },
  approved: { label: "已批准", cls: "info" },
  rendering: { label: "渲染中", cls: "run" },
  rendered: { label: "已渲染", cls: "info" },
  completed: { label: "已入库", cls: "ok" },
  failed: { label: "失败", cls: "err" },
  needs_attention: { label: "需处理", cls: "err" },
};

const TASK_STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "排队中", cls: "" },
  running: { label: "执行中", cls: "run" },
  succeeded: { label: "成功", cls: "ok" },
  failed: { label: "失败", cls: "err" },
  cancelled: { label: "已取消", cls: "" },
};

const OUTPUT_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "草稿 · 待验收", cls: "warn" },
  rendering: { label: "渲染中", cls: "run" },
  gates_failed: { label: "未过闸", cls: "err" },
  gates_passed: { label: "过机器闸", cls: "warn" },
  reviewed: { label: "已审片", cls: "info" },
  completed: { label: "过闸入库", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

const ENGINE_LABEL: Record<string, string> = {
  shotcraft: "宣传片",
  talkcraft: "口播观点",
};

export function projectStatus(status: string) {
  return PROJECT_STATUS[status] ?? { label: status, cls: "" };
}
export function taskStatus(status: string) {
  return TASK_STATUS[status] ?? { label: status, cls: "" };
}
export function outputStatus(status: string) {
  return OUTPUT_STATUS[status] ?? { label: status, cls: "" };
}
export function engineLabel(engine: string) {
  return ENGINE_LABEL[engine] ?? engine;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const rounded = Math.round(seconds);
  const m = Math.floor(rounded / 60);
  const s = rounded % 60;
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function framesToDuration(frames: number, fps: number): string {
  if (!Number.isFinite(frames) || !Number.isFinite(fps) || frames < 0 || fps <= 0) return "—";
  return formatDuration(frames / fps);
}
