<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Download, Film, Search } from "lucide-vue-next";
import { api, errorMessage, outputCoverUrl, outputFileUrl, outputPosterUrl } from "../api";
import type { GateEntry, RenderOutput } from "../types";
import { engineLabel, formatDateTime, framesToDuration, outputStatus } from "../utils";

const route = useRoute();
const router = useRouter();
const outputs = ref<RenderOutput[]>([]);
const engine = ref("");
const status = ref("");
const keyword = ref("");
const selected = ref<RenderOutput | null>(null);
const error = ref("");
const loading = ref(true);
let disposed = false;
let refreshing = false;
let hasLoaded = false;

const coverBusy = ref(false);
const coverMsg = ref("");
let pollTimer: number | undefined;

function selectFromQuery() {
  const value = route.query.output;
  const id = typeof value === "string" && /^\d+$/.test(value) ? Number(value) : NaN;
  selected.value = Number.isSafeInteger(id) && id > 0
    ? outputs.value.find((output) => output.id === id) ?? null
    : null;
  coverMsg.value = "";
}

async function updateOutputQuery(id?: number) {
  const query = { ...route.query };
  if (id === undefined) delete query.output;
  else query.output = String(id);
  try {
    await router.replace({ query });
  } catch (e) {
    error.value = errorMessage(e);
  }
}

function openOutput(output: RenderOutput) {
  selected.value = output;
  coverMsg.value = "";
  void updateOutputQuery(output.id);
}

function closeOutput() {
  selected.value = null;
  coverMsg.value = "";
  if (route.query.output !== undefined) void updateOutputQuery();
}

watch(() => route.query.output, selectFromQuery);

function hasCover(o: RenderOutput | null): boolean {
  return !!o && o.cover_status === "ready";
}
function coverPending(o: RenderOutput | null): boolean {
  return !!o && (o.cover_status === "queued" || o.cover_status === "running");
}
function coverLabel(o: RenderOutput | null): { text: string; cls: string } {
  if (!o) return { text: "", cls: "" };
  if (o.cover_status === "ready") return { text: "AI 封面", cls: "ok" };
  if (o.cover_status === "failed") return { text: "封面失败", cls: "err" };
  if (coverPending(o)) return { text: "封面生成中", cls: "warn" };
  return { text: "", cls: "" };
}

async function refreshOutputs() {
  if (refreshing || disposed) return;
  refreshing = true;
  try {
  const result = await api.outputs({});
  if (disposed) return;
  outputs.value = result;
  error.value = "";
  if (!hasLoaded) {
    hasLoaded = true;
    selectFromQuery();
  } else if (selected.value) {
    selected.value = outputs.value.find((o) => o.id === selected.value!.id) ?? null;
  }
  } catch (e) {
    if (!disposed) error.value = errorMessage(e);
  } finally {
    refreshing = false;
    loading.value = false;
  }
}
function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
}
function startPoll() {
  if (pollTimer || disposed) return;
  pollTimer = window.setInterval(async () => {
    if (!outputs.value.some((o) => coverPending(o))) {
      stopPoll();
      return;
    }
    try {
      await refreshOutputs();
    } catch {
      /* 轮询失败下轮再试 */
    }
  }, 3000);
}

async function regenCover() {
  if (!selected.value || coverBusy.value || coverPending(selected.value)) return;
  const outputId = selected.value.id;
  coverBusy.value = true;
  coverMsg.value = "";
  try {
    const updated = await api.generateCover(outputId);
    if (disposed) return;
    if (selected.value?.id === outputId) coverMsg.value = "封面任务已提交，生成中…";
    const idx = outputs.value.findIndex((o) => o.id === updated.id);
    if (idx >= 0) outputs.value[idx] = updated;
    if (selected.value?.id === outputId) selected.value = updated;
    startPoll();
  } catch (e) {
    if (!disposed && selected.value?.id === outputId) coverMsg.value = errorMessage(e);
  } finally {
    coverBusy.value = false;
  }
}

const filtered = computed(() =>
  outputs.value.filter((o) => {
    if (engine.value && o.engine !== engine.value) return false;
    if (status.value && o.status !== status.value) return false;
    const kw = keyword.value.trim().toLowerCase();
    if (kw) {
      const hay = `${o.id} ${o.engine} ${engineLabel(o.engine)} ${o.status} ${o.sha256}`.toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  }),
);

function gateBadge(s: string) {
  return s === "pass" ? "ok" : s === "fail" ? "err" : s === "skipped" ? "warn" : "";
}
function gateLabel(s: string) {
  return s === "pass" ? "PASS" : s === "fail" ? "FAIL" : s === "skipped" ? "SKIP" : "ERR";
}
function gatesOf(o: RenderOutput | null): GateEntry[] {
  return o?.gates_json?.gates ?? [];
}

type ReviewFinding = { id: string; status: string; detail: string };
function reviewFindings(o: RenderOutput | null): ReviewFinding[] {
  const r = (o?.review_json ?? {}) as { findings?: ReviewFinding[] };
  return r.findings ?? [];
}
function reviewMode(o: RenderOutput | null): string {
  const r = (o?.review_json ?? {}) as { mode?: string; enabled?: boolean };
  if (!r.mode) return "";
  return r.enabled ? r.mode : "清单";
}
function reviewPassed(o: RenderOutput | null): boolean {
  const r = (o?.review_json ?? {}) as { passed?: boolean };
  return Boolean(r.passed);
}

onMounted(async () => {
  await refreshOutputs();
  if (outputs.value.some((o) => coverPending(o))) startPoll();
});
onUnmounted(() => {
  disposed = true;
  stopPoll();
});
</script>

<template>
  <div class="stack">
    <div class="row between wrap">
      <h1>成片库</h1>
      <div class="row">
        <label class="search">
          <Search :size="14" />
          <input v-model="keyword" class="input" placeholder="关键词 / id / sha" />
        </label>
        <select v-model="status" class="input" style="max-width: 150px">
          <option value="">全部状态</option>
          <option value="gates_passed">仅过机器闸</option>
          <option value="reviewed">已审片</option>
          <option value="completed">过闸入库</option>
          <option value="gates_failed">未过闸</option>
          <option value="failed">失败</option>
        </select>
        <select v-model="engine" class="input" style="max-width: 150px">
          <option value="">全部引擎</option>
          <option value="shotcraft">宣传片</option>
          <option value="talkcraft">口播观点</option>
        </select>
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn sm" @click="refreshOutputs">重试</button></p>
    <div v-if="filtered.length" class="grid cols-3">
      <button v-for="o in filtered" :key="o.id" class="card output" @click="openOutput(o)">
        <div class="thumb">
            <img v-if="hasCover(o)" :src="outputCoverUrl(o.id)" alt="" />
            <img v-else-if="o.poster_path" :src="outputPosterUrl(o.id)" alt="" />
          <Film v-else :size="28" color="#555" />
          <span class="badge" :class="outputStatus(o.status).cls">
            {{ outputStatus(o.status).label }}
          </span>
          <span v-if="coverLabel(o).text" class="badge cover-badge" :class="coverLabel(o).cls">
            {{ coverLabel(o).text }}
          </span>
        </div>
        <div class="row between">
          <strong>{{ engineLabel(o.engine) }}</strong>
          <span class="mono muted">{{ framesToDuration(o.duration_frames, o.fps) }}</span>
        </div>
        <div class="muted">{{ o.width }}×{{ o.height }} · {{ o.fps }}fps · {{ formatDateTime(o.created_at) }}</div>
      </button>
    </div>
    <div v-else-if="!error" class="card">
      <p class="muted">{{ loading ? '正在加载成片…' : outputs.length ? '没有符合筛选条件的成片，试试调整筛选条件。' : '成片库还是空的。产出的视频会出现在这里。' }}</p>
    </div>

    <div v-if="selected" class="modal" @click.self="closeOutput">
      <div class="modal-card card">
        <div class="row between">
          <h2>
            {{ engineLabel(selected.engine) }} #{{ selected.id }}
            <span class="badge" :class="outputStatus(selected.status).cls">
              {{ outputStatus(selected.status).label }}
            </span>
          </h2>
          <button class="btn sm" @click="closeOutput">关闭</button>
        </div>
          <video :src="outputFileUrl(selected.id)" controls autoplay class="player" />
        <div class="meta grid cols-2">
          <div><span class="muted">分辨率</span> {{ selected.width }}×{{ selected.height }}</div>
          <div><span class="muted">帧率</span> {{ selected.fps }} fps</div>
          <div><span class="muted">时长</span> {{ framesToDuration(selected.duration_frames, selected.fps) }}</div>
          <div><span class="muted">状态</span> {{ outputStatus(selected.status).label }}</div>
          <div style="grid-column: span 2">
            <span class="muted">关联</span>
            <router-link :to="`/projects/${selected.project_id}`" class="link">
              项目 #{{ selected.project_id }}
            </router-link>
            · 版本 #{{ selected.version_id }}
          </div>
          <div style="grid-column: span 2"><span class="muted">SHA-256</span> <span class="mono">{{ selected.sha256 }}</span></div>
        </div>

        <div>
          <div class="row between">
            <h3>质检报告</h3>
            <span
              v-if="gatesOf(selected).length"
              class="badge"
              :class="selected.gates_json?.passed ? 'ok' : selected.gates_json?.blocking ? 'err' : 'warn'"
            >
              {{ selected.gates_json?.passed ? "全部通过" : selected.gates_json?.blocking ? "未过·阻塞入库" : "未过·告警入库" }}
            </span>
          </div>
          <template v-if="gatesOf(selected).length">
            <div v-for="g in gatesOf(selected)" :key="g.key" class="gate-row">
              <span class="badge" :class="gateBadge(g.status)">{{ gateLabel(g.status) }}</span>
              <div class="gate-body">
                <div class="gate-name">{{ g.name }}</div>
                <div class="muted small">{{ g.detail }}</div>
              </div>
            </div>
          </template>
          <p v-else class="muted small">该成片没有机器闸记录。</p>
        </div>

        <div v-if="reviewFindings(selected).length">
          <div class="row between">
            <h3>独立审片（模式 B）</h3>
            <span class="badge" :class="reviewPassed(selected) ? 'ok' : 'err'">
              {{ reviewMode(selected) }} ·
              {{ reviewFindings(selected).filter((f) => f.status === "✓").length }}/{{ reviewFindings(selected).length }} 通过
            </span>
          </div>
          <div v-for="f in reviewFindings(selected)" :key="f.id" class="gate-row">
            <span class="badge" :class="f.status === '✓' ? 'ok' : 'err'">{{ f.status }}</span>
            <div class="gate-body">
              <div class="gate-name">{{ f.id }}</div>
              <div class="muted small">{{ f.detail }}</div>
            </div>
          </div>
        </div>

        <div>
          <div class="row between">
            <h3>AI 主题封面</h3>
            <span v-if="hasCover(selected)" class="badge ok">已生成</span>
            <span v-else-if="coverPending(selected)" class="badge warn">生成中…</span>
            <span v-else-if="selected.cover_status === 'failed'" class="badge err">生成失败</span>
          </div>
          <img v-if="hasCover(selected)" :src="outputCoverUrl(selected.id)" class="cover-img" alt="主题封面" />
          <p v-if="selected.cover_error" class="error small">{{ selected.cover_error }}</p>
          <div class="row wrap" style="gap: 8px; margin-top: 8px">
            <button class="btn" :disabled="coverBusy || coverPending(selected)" @click="regenCover">
              {{ hasCover(selected) ? "重新生成封面" : "生成封面" }}
            </button>
            <a v-if="hasCover(selected)" :href="outputCoverUrl(selected.id)" download class="btn">
              <Download :size="14" /> 下载封面
            </a>
          </div>
          <p v-if="coverMsg" class="muted small">{{ coverMsg }}</p>
        </div>

        <div class="row">
          <a :href="outputFileUrl(selected.id)" download class="btn primary">
            <Download :size="14" /> 下载 mp4
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.output {
  text-align: left;
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.output > .row,
.output > .muted {
  padding: 0 14px;
}
.output > .muted {
  padding-bottom: 14px;
}
.thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #111;
  display: grid;
  place-items: center;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb .badge {
  position: absolute;
  top: 8px;
  left: 8px;
}
.thumb .cover-badge {
  left: auto;
  right: 8px;
}
.cover-img {
  width: 100%;
  border-radius: var(--radius-sm);
  display: block;
}
.search {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
}
.search .input {
  width: 180px;
}
.modal {
  position: fixed;
  inset: 0;
  background: rgba(16, 16, 32, 0.45);
  display: grid;
  place-items: center;
  padding: 24px;
  z-index: 50;
}
.modal-card {
  width: min(880px, 100%);
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.player {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: var(--radius-sm);
}
.meta {
  font-size: 13px;
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
.link {
  color: var(--accent);
  text-decoration: underline;
}
.error {
  color: var(--err);
}
</style>
