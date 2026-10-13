<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { CheckCircle2, RefreshCw, Play } from "lucide-vue-next";
import { api, errorMessage, outputCoverUrl, outputFileUrl, projectStreamUrl } from "../api";
import type { AgentRunSummary, GatesJson, PipelineEvent, PipelineTask, RenderOutput, VideoProjectDetail } from "../types";
import { formatDateTime, formatDuration, projectStatus } from "../utils";

type StreamPayload = {
  project: Partial<VideoProjectDetail>;
  task: Partial<PipelineTask> | null;
  events: { id: number; level: string; message: string; created_at: string | null }[];
  done: boolean;
};

const route = useRoute();
const projectId = computed(() => Number(route.params.id));

const project = ref<VideoProjectDetail | null>(null);
const task = ref<PipelineTask | null>(null);
const events = ref<PipelineEvent[]>([]);
const outputs = ref<RenderOutput[]>([]);
const error = ref("");
const busy = ref(false);
const live = ref(false);
const loading = ref(false);
const taskActive = computed(() => !!task.value && ["queued", "running"].includes(task.value.status));
let timer: number | undefined;
let es: EventSource | undefined;
let disposed = false;
let loadRequest = 0;

const AGENT_SCENES: { key: string; label: string }[] = [
  { key: "plan", label: "规划" },
  { key: "build_verify", label: "制作与检查" },
  { key: "deliver", label: "验收交付" },
];

const stageList = computed(() => AGENT_SCENES);

const currentStage = computed(() => {
  const phase = project.value?.agent_summary?.phase;
  if (phase && AGENT_SCENES.some((s) => s.key === phase)) return phase;
  if (project.value?.status === "rendered" || project.value?.status === "completed") return "deliver";
  return "plan";
});

const stageIndex = computed(() => stageList.value.findIndex((s) => s.key === currentStage.value));

function stageClass(key: string) {
  const idx = stageList.value.findIndex((s) => s.key === key);
  const status = project.value?.status;
  if (status === "failed" && idx === 0) return "failed";
  if (status === "needs_attention" && idx === stageIndex.value) return "failed";
  if (status === "rendered" || status === "completed") return "done";
  if (idx < stageIndex.value) return "done";
  if (idx === stageIndex.value) return "active";
  return "";
}

const agentSummary = computed<AgentRunSummary | null>(() => project.value?.agent_summary ?? null);
const agentUsage = computed(() => agentSummary.value?.usage);
const agentPhase = computed(() => {
  const labels: Record<string, string> = {plan: '确定方案', build: '制作与检查', local_qa: '制作与检查',
    visual_qa: '验收交付', finalize: '验收交付', build_verify: '制作与检查', deliver: '验收交付'};
  return labels[agentSummary.value?.phase || ''] || agentSummary.value?.phase_label || '阶段未知';
});
const agentCandidateState = computed(() => ({none: '暂无候选', draft: '草稿，未通过验收',
  technical_pass_pending_review: '技术检查通过，待完成审片', accepted: '完成验收'}[agentSummary.value?.candidate_status || ''] || '旧记录，需核验'));
const agentSubstate = computed(() => ({typescript: '正在编译', composition_stills: '正在核对场景静帧',
  still_review: '正在核对静帧内容', rendering: '正在渲染', visual_review: '正在审片'}[agentSummary.value?.substate || ''] || ''));
const agentStillState = computed(() => {
  const status = agentSummary.value?.still_qa?.status;
  return status === 'pass' ? '静帧预审通过' : status === 'fail' ? '静帧预审未通过' : '静帧预审未执行';
});
const agentFinalState = computed(() => {
  const status = agentSummary.value?.visual_qa?.status;
  return status === 'pass' ? '最终视频审片通过' : status === 'fail' ? '最终视频审片未通过' : '最终视频审片未执行';
});
function stopLabel(code: string) {
  const labels: Record<string, string> = {network_error: '网络失败', timeout: '调用超时', model_truncated: '模型输出截断',
    model_empty: '模型无可执行调用', no_progress: '无进展停止', tool_failures: '连续工具失败',
    compile_failed: '编译失败', budget_exhausted: '预算用尽', plan_incomplete: '方案未完成',
    deadline_insufficient: '剩余时间不足，已保留草稿', model_timeout: '模型调用超时', scene_unfinished: '场景制作未完成',
    review_blocker: '审片阻断', review_invalid: '审片报告不可用', internal_error: '内部异常', cancelled: '已取消'};
  return labels[code] || code;
}
function tokenText(value: number | undefined) {
  if (!value) return "0";
  return value >= 1_000_000 ? `${(value / 1_000_000).toFixed(2)}M` : value >= 1_000 ? `${(value / 1_000).toFixed(1)}K` : String(value);
}
function agentRunState(summary: AgentRunSummary | null) {
  if (!summary) return "尚未开始";
  if (summary.status === "completed") return "成片完成验收";
  if (summary.status === "cancelled") return "已取消，候选已保留";
  if (summary.status === "needs_attention") return "需要处理阻断项";
  return `正在${agentPhase.value}`;
}

const latestOutput = computed(() => outputs.value[0] || null);
const gateReport = computed<GatesJson | null>(() => latestOutput.value?.gates_json || null);
const audioWarnings = computed(() => {
  const warnings = gateReport.value?.tts?.warnings;
  return Array.isArray(warnings) ? warnings.map(String) : [];
});

const coverBusy = ref(false);
const coverMsg = ref("");
let coverTimer: number | undefined;

function hasCover(o: RenderOutput | null): boolean {
  return !!o && o.cover_status === "ready";
}
function coverPending(o: RenderOutput | null): boolean {
  return !!o && (o.cover_status === "queued" || o.cover_status === "running");
}
function stopCoverPoll() {
  if (coverTimer) {
    clearInterval(coverTimer);
    coverTimer = undefined;
  }
}
function startCoverPoll() {
  if (coverTimer || disposed) return;
  coverTimer = window.setInterval(async () => {
    if (!coverPending(latestOutput.value)) {
      stopCoverPoll();
      return;
    }
    try {
      if (!loading.value) await load();
    } catch {
      /* 轮询失败下轮再试 */
    }
  }, 3000);
}
async function regenCover() {
  if (!latestOutput.value || coverBusy.value || coverPending(latestOutput.value)) return;
  const id = projectId.value;
  coverBusy.value = true;
  coverMsg.value = "";
  try {
    await api.generateCover(latestOutput.value.id);
    if (disposed || projectId.value !== id) return;
    coverMsg.value = "封面任务已提交，生成中…";
    await load();
    startCoverPoll();
  } catch (e) {
    if (!disposed && projectId.value === id) coverMsg.value = errorMessage(e);
  } finally {
    coverBusy.value = false;
  }
}

function gateBadge(status: string) {
  return status === "pass" ? "ok" : status === "fail" ? "err" : status === "skipped" ? "warn" : "";
}
function gateLabel(status: string) {
  return status === "pass" ? "PASS" : status === "fail" ? "FAIL" : status === "skipped" ? "SKIP" : "ERR";
}

async function load() {
  if (disposed) return;
  const id = projectId.value;
  const request = ++loadRequest;
  loading.value = true;
  error.value = "";
  try {
    const [nextProject, allOutputs] = await Promise.all([api.project(id), api.outputs({})]);
    if (disposed || request !== loadRequest) return;
    const [nextTask, nextEvents] = nextProject.latest_task_id
      ? await Promise.all([api.task(nextProject.latest_task_id), api.taskEvents(nextProject.latest_task_id)])
      : [null, []];
    if (disposed || request !== loadRequest) return;
    project.value = nextProject;
    outputs.value = allOutputs.filter((o) => o.project_id === id);
    task.value = nextTask;
    events.value = nextEvents;
    if (coverPending(latestOutput.value)) startCoverPoll();
    else stopCoverPoll();
  } catch (e) {
    if (!disposed && request === loadRequest) error.value = errorMessage(e);
  } finally {
    if (!disposed && request === loadRequest) loading.value = false;
  }
}

function stopStream() {
  if (es) {
    es.close();
    es = undefined;
  }
  live.value = false;
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

function startPolling() {
  if (timer || disposed) return;
  timer = window.setInterval(() => { if (!loading.value) void load(); }, 3000);
}

function applyStream(data: StreamPayload) {
  if (project.value) {
    project.value = { ...project.value, ...data.project } as VideoProjectDetail;
  }
  task.value = data.task
    ? ({ ...(task.value ?? {}), ...data.task } as PipelineTask)
    : null;
  events.value = data.events.map((e) => ({
    id: e.id,
    task_id: data.task?.id ?? 0,
    level: e.level,
    message: e.message,
    data_json: {},
    created_at: e.created_at ?? "",
  })) as PipelineEvent[];
  if (data.done) {
    stopStream();
    stopPolling();
    void load();
  }
}

function startStream() {
  if (disposed) return;
  stopStream();
  stopPolling();
  try {
    const source = new EventSource(projectStreamUrl(projectId.value));
    es = source;
    source.onopen = () => {
      if (es !== source || disposed) return;
      live.value = true;
    };
    source.onmessage = (ev) => {
      if (es !== source || disposed) return;
      try {
        applyStream(JSON.parse(ev.data) as StreamPayload);
      } catch {
        /* 忽略单帧解析错误 */
      }
    };
    source.onerror = () => {
      if (es !== source || disposed) return;
      stopStream();
      startPolling();
    };
  } catch {
    startPolling();
  }
}

async function regenerate() {
  if (busy.value || taskActive.value) return;
  if (!confirm("整片重生成？将基于当前需求重新生成规格并产出新版本。")) return;
  const id = projectId.value;
  busy.value = true;
  try {
    await api.regenerateProject(id, {});
    if (disposed || projectId.value !== id) return;
    await load();
  } catch (e) {
    if (!disposed && projectId.value === id) error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function render() {
  if (busy.value || !task.value || !["failed", "cancelled"].includes(task.value.status)) return;
  const id = projectId.value;
  busy.value = true;
  error.value = "";
  try {
    await api.retryTask(task.value.id);
    if (disposed || projectId.value !== id) return;
    await load();
    if (["generating", "rendering"].includes(project.value?.status ?? "")) startStream();
  } catch (e) {
    if (!disposed && projectId.value === id) error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function approveProject() {
  if (busy.value) return;
  if (!confirm("确认审核通过当前版本？通过后项目状态会变为“已批准”。")) return;
  const id = projectId.value;
  busy.value = true;
  error.value = "";
  try {
    const result = await api.approveProject(id);
    if (!disposed && projectId.value === id) project.value = result;
  } catch (e) {
    if (!disposed && projectId.value === id) error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

watch(
  () => project.value?.status,
  (status) => {
    if (status === "generating" || status === "rendering") {
      startStream();
    } else {
      stopStream();
      stopPolling();
    }
  },
);

watch(projectId, () => {
  loadRequest++;
  stopStream();
  stopPolling();
  stopCoverPoll();
  project.value = null;
  task.value = null;
  events.value = [];
  outputs.value = [];
  coverMsg.value = "";
  void load();
}, { immediate: true });
onUnmounted(() => {
  disposed = true;
  stopStream();
  stopPolling();
  stopCoverPoll();
});
</script>

<template>
  <div v-if="project" class="stack">
    <div class="row between wrap">
      <div>
        <h1>{{ project.title || project.topic }}</h1>
        <div class="muted">
          {{ project.topic }} · 目标 {{ formatDuration(project.duration_target_sec) }} ·
          {{ project.lang === "zh" ? "中文" : "English" }}
        </div>
      </div>
      <div class="row">
        <span class="badge" :class="projectStatus(project.status).cls">
          {{ projectStatus(project.status).label }}
        </span>
        <button class="btn" :disabled="busy || taskActive" @click="regenerate">
          <RefreshCw :size="14" /> 整片重生成
        </button>
        <button
          class="btn primary"
          :disabled="busy || !task || !['failed', 'cancelled'].includes(task.status)"
          @click="render"
        >
          <Play :size="14" /> 继续精修
        </button>
        <button
          v-if="project.status === 'pending_review'"
          class="btn primary"
          :disabled="busy"
          @click="approveProject"
        >
          <CheckCircle2 :size="14" /> 审核通过并继续精修
        </button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="card stack">
      <h2>画面与声音</h2>
      <div class="row">
        <span v-if="project.theme_json?.accent">主题色 <span :style="{ color: project.theme_json.accent }">●</span> {{ project.theme_json.accent }}</span>
        <span v-else>主题色：继承风格</span>
        <span>BGM：{{ project.bgm_enabled == null ? '继承风格' : project.bgm_enabled ? '开启' : '关闭' }}</span>
        <span>中文旁白：{{ project.tts_enabled == null ? '继承默认设置' : project.tts_enabled ? '开启' : '关闭' }}</span>
        <span v-if="project.tts_enabled && !project.tts_asset_id">语速：{{ project.tts_rate == null ? '跟随后台默认' : (project.tts_rate > 0 ? `+${project.tts_rate}%` : `${project.tts_rate}%`) }}</span>
        <span v-if="project.tts_asset_id">使用上传旁白</span>
      </div>
      <p v-for="(warning, index) in audioWarnings" :key="index" class="error">配音提示：{{ warning }}</p>
    </div>

    <div class="card">
      <div class="row between">
        <h2>流程进度</h2>
        <span class="muted mono" v-if="task">任务 #{{ task.id }} · {{ task.status }}<template v-if="live"> · 实时</template></span>
      </div>
      <div class="timeline">
        <template v-for="(s, i) in stageList" :key="s.key">
          <span class="node" :class="stageClass(s.key)">
            <span class="dot"></span>
            {{ s.label }}
          </span>
          <span v-if="i < stageList.length - 1" class="sep">→</span>
        </template>
      </div>
      <p v-if="task?.error_message" class="error" style="margin-top: 10px">
        {{ task.error_code }}：{{ task.error_message }}
      </p>
    </div>

    <div class="card">
      <div class="row between">
        <h2>Agent 运行摘要</h2>
        <span class="badge" :class="agentSummary?.status === 'completed' ? 'ok' : agentSummary?.status === 'needs_attention' ? 'warn' : ''">
          {{ agentRunState(agentSummary) }}
        </span>
      </div>
      <div v-if="agentSummary" class="agent-summary-grid">
        <div><span class="muted small">阶段</span><strong>{{ agentPhase }}{{ agentSummary.convergence_mode ? ' · 收敛中' : '' }}</strong><span class="muted small">{{ agentSummary.status === 'running' ? agentSubstate : '' }}</span></div>
        <div><span class="muted small">轮数</span><strong>{{ agentSummary.iteration }} / {{ agentSummary.max_iters }}</strong></div>
        <div><span class="muted small">同版本累计 token / 上限</span><strong>{{ tokenText(agentUsage?.total_tokens) }} / {{ tokenText(agentUsage?.total_budget) }}</strong></div>
        <div><span class="muted small">本次启动消耗 token</span><strong>{{ agentSummary.invocation_usage ? tokenText(agentSummary.invocation_usage.total_tokens) : '旧记录未区分' }}</strong></div>
        <div><span class="muted small">剩余时间</span><strong>{{ agentSummary.remaining_seconds ?? '—' }} 秒</strong></div>
        <div><span class="muted small">成片状态</span><strong>{{ agentCandidateState }}</strong></div>
        <div><span class="muted small">候选 / 终检 / 整片渲染</span><strong>{{ agentSummary.candidate_count }} / {{ agentSummary.inspections }} / {{ agentSummary.render_attempts }}</strong><span class="muted small" v-if="agentSummary.granted_renders">续跑授予 +{{ agentSummary.granted_renders }} 次渲染</span></div>
        <div><span class="muted small">静帧预审</span><strong>{{ agentStillState }}</strong><span class="muted small">已用 {{ agentSummary.still_reviews ?? 0 }} 次</span></div>
        <div v-if="agentSummary.render_concurrency"><span class="muted small">本次渲染帧并发</span><strong>{{ agentSummary.render_concurrency }}</strong><span class="muted small">{{ agentSummary.render_concurrency_reason }}</span></div>
        <div v-if="agentSummary.check_ready_last?.elapsed_seconds != null"><span class="muted small">最近就绪检查</span><strong>{{ agentSummary.check_ready_last.elapsed_seconds }} 秒</strong><span class="muted small">{{ agentSummary.check_ready_last.readiness_cached ? '复用已有检查结果' : agentSummary.check_ready_last.check_ready_bundle_cached ? '复用打包缓存' : '执行就绪检查' }} · {{ agentSummary.check_ready_last.ok ? '通过' : '未通过' }}</span></div>
        <div><span class="muted small">最终视频审片</span><strong>{{ agentFinalState }}</strong></div>
        <div><span class="muted small">制作模型</span><strong>{{ tokenText(agentUsage?.production?.total_tokens) }}</strong></div>
        <div><span class="muted small">审片模型</span><strong>{{ tokenText(agentUsage?.review?.total_tokens) }}</strong></div>
      </div>
      <p v-if="agentSummary" class="muted small" style="margin-top: 10px">
        最近工具：<span class="mono">{{ agentSummary.last_tool || '—' }}</span>
        · 输入 {{ tokenText(agentUsage?.prompt_tokens) }} · 输出 {{ tokenText(agentUsage?.completion_tokens) }}
      </p>
      <template v-if="agentSummary">
        <p v-if="agentSummary.last_progress" class="muted small">最近进展：第 {{ agentSummary.last_progress.iteration }} 轮 · {{ agentSummary.last_progress.tool }}</p>
        <p v-if="agentSummary.stop_reason" class="error">{{ stopLabel(agentSummary.stop_reason.code) }}：{{ agentSummary.stop_reason.detail }}</p>
        <p v-if="agentSummary.stop_reason?.code === 'review_blocker'" class="muted small">点击“继续精修”可续跑，续跑会额外放行 1 次整片渲染额度（需人工确认）。</p>
        <p v-for="(entry, index) in (agentSummary.render_ledger || []).slice(-5)" :key="index" class="muted small">
          渲染台账 #{{ entry.attempt }} · {{ entry.reason === 'initial' ? '初始' : entry.reason === 'review_fix' ? '修复' : '续跑授予' }}<span v-if="entry.blockers_before != null"> · 渲染前 blocker {{ entry.blockers_before }}</span>
        </p>
        <p v-for="(blocker, index) in agentSummary.blockers || []" :key="index" class="muted small">待处理：{{ blocker }}</p>
        <p v-if="agentSummary.unknown_usage_responses" class="muted small">{{ agentSummary.unknown_usage_responses }} 次响应的用量未知，累计 token 仅含已知用量。</p>
        <p v-if="agentSummary.candidate_stale" class="muted small">当前源码或音频已变化；旧候选保留为草稿，需重新验收。</p>
        <p class="muted small">继续精修沿用同版本剩余额度，不刷新轮数、token、渲染、审片和截止时间。任务结束后，草稿仍需通过成片验收。</p>
      </template>
      <p v-else class="muted">暂无运行摘要；Agent 启动后会显示阶段、预算、候选和最近工具。</p>
    </div>

    <div class="card">
      <h2>成片预览</h2>
      <p v-if="latestOutput?.status === 'draft'" class="muted">草稿已保存，尚未通过交付验收。可以预览，或点击“继续精修”从已保存工程恢复。</p>
      <div v-if="latestOutput" class="preview">
            <video :src="outputFileUrl(latestOutput.id)" controls />
      </div>
      <div v-else class="preview placeholder">
        <span class="muted">尚无视频；首次整片渲染成功后会在这里显示。</span>
      </div>

      <div v-if="latestOutput" class="cover-block">
        <div class="row between">
          <h3>AI 主题封面</h3>
          <span v-if="hasCover(latestOutput)" class="badge ok">已生成</span>
          <span v-else-if="coverPending(latestOutput)" class="badge warn">生成中…</span>
          <span v-else-if="latestOutput.cover_status === 'failed'" class="badge err">生成失败</span>
        </div>
        <img v-if="hasCover(latestOutput)" :src="outputCoverUrl(latestOutput.id)" class="cover-img" alt="主题封面" />
        <p v-else class="muted small">
          渲染成功后会自动生成一张符合主题的炫酷封面；也可手动生成或换模型重生成。
        </p>
        <p v-if="latestOutput.cover_error" class="error small">{{ latestOutput.cover_error }}</p>
        <div class="row wrap" style="gap: 8px; margin-top: 8px">
          <button class="btn" :disabled="coverBusy || coverPending(latestOutput)" @click="regenCover">
            {{ hasCover(latestOutput) ? "重新生成封面" : "生成封面" }}
          </button>
          <a v-if="hasCover(latestOutput)" :href="outputCoverUrl(latestOutput.id)" download class="btn">
            下载封面
          </a>
        </div>
        <p v-if="coverMsg" class="muted small">{{ coverMsg }}</p>
      </div>
    </div>

    <div class="card">
      <div class="row between">
        <h2>质检报告</h2>
        <span
          v-if="gateReport && gateReport.gates && gateReport.gates.length"
          class="badge"
          :class="gateReport.passed ? 'ok' : gateReport.blocking ? 'err' : 'warn'"
        >
          {{ latestOutput?.status === 'draft' ? '草稿 · 尚待验收' : gateReport.passed ? "全部通过" : gateReport.blocking ? "未过·阻塞入库" : "未过·告警入库" }}
        </span>
      </div>
      <template v-if="gateReport && gateReport.gates && gateReport.gates.length">
        <div v-for="g in gateReport.gates" :key="g.key" class="gate-row">
          <span class="badge" :class="gateBadge(g.status)">{{ gateLabel(g.status) }}</span>
          <div class="gate-body">
            <div class="gate-name">{{ g.name }}</div>
            <div class="muted small">{{ g.detail }}</div>
          </div>
        </div>
      </template>
      <p v-else class="muted">
        尚无质检结果。渲染后会自动跑引擎原生质检闸（帧数/音轨、静止、构图/光），未过闸按配置决定是否入库。
      </p>
    </div>

    <div class="card" v-if="events.length">
      <h2>事件日志</h2>
      <div class="log">
        <div v-for="e in events" :key="e.id" class="log-line">
          <span class="muted mono">{{ formatDateTime(e.created_at) }}</span>
          <span class="badge" :class="e.level === 'error' ? 'err' : e.level === 'warning' ? 'warn' : ''">
            {{ e.level }}
          </span>
          <span>{{ e.message }}</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="card stack">
    <p :class="error ? 'error' : 'muted'" role="status">{{ error || '加载中…' }}</p>
    <button v-if="error" class="btn" :disabled="loading" @click="load">重新加载</button>
    <router-link v-if="error" :to="{ name: 'projects' }">返回需求列表</router-link>
  </div>
</template>

<style scoped>
.preview {
  margin-top: 10px;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.preview video {
  width: 100%;
  height: 100%;
}
.cover-block {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.cover-img {
  width: 100%;
  max-width: 420px;
  margin-top: 8px;
  border-radius: var(--radius-sm);
  display: block;
}
.placeholder {
  display: grid;
  place-items: center;
  background: var(--surface-2);
  border: 1px dashed var(--border);
}
.error {
  color: var(--err);
}
.agent-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.agent-summary-grid > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}
@media (max-width: 760px) {
  .agent-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.gate-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.gate-row:last-child {
  border-bottom: none;
}
.gate-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.gate-name {
  font-weight: 600;
}
.log {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}
.log-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
</style>
