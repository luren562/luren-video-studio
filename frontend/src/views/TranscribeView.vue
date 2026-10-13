<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Check, Copy, Download, FileText, Link2, Loader2, Trash2, Upload } from "lucide-vue-next";
import { api, errorMessage, transcriptionFileUrl } from "../api";
import type { TranscriptionJob, TranscriptionSummary } from "../types";
import { formatDateTime, formatDuration } from "../utils";

const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "排队中", cls: "" },
  running: { label: "识别中", cls: "run" },
  succeeded: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

const jobs = ref<TranscriptionSummary[]>([]);
const detail = ref<TranscriptionJob | null>(null);
const error = ref("");
const mode = ref<"upload" | "url">("upload");
const language = ref("zh");
const title = ref("");
const url = ref("");
const file = ref<File | null>(null);
const submitting = ref(false);
const uploadPercent = ref(0);
const copied = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const removing = ref<number | null>(null);
let timer: number | undefined;
let copyTimer: number | undefined;
let disposed = false;
let refreshing = false;
let listRequest = 0;
let detailRequest = 0;
let selectedId: number | null = null;

const busy = computed(() => jobs.value.some((j) => j.status === "queued" || j.status === "running"));
const textLength = computed(() => (detail.value?.text ?? "").length);

function statusOf(status: string) {
  return STATUS[status] ?? { label: status, cls: "" };
}

async function load() {
  const request = ++listRequest;
  const result = await api.transcriptions();
  if (!disposed && request === listRequest) jobs.value = result;
}

async function select(id: number) {
  const request = ++detailRequest;
  if (selectedId !== id) {
    detail.value = null;
    copied.value = false;
  }
  selectedId = id;
  try {
    const result = await api.transcription(id);
    if (!disposed && request === detailRequest) detail.value = result;
  } catch (e) {
    if (!disposed && request === detailRequest) error.value = errorMessage(e);
  }
}

async function refresh() {
  if (refreshing || disposed) return;
  refreshing = true;
  try {
    await load();
    if (detail.value) {
      const job = jobs.value.find((j) => j.id === detail.value?.id);
      if (job && job.status !== detail.value.status) {
        await select(detail.value.id);
      }
    }
  } catch (e) {
    if (!disposed) error.value = errorMessage(e);
  } finally {
    refreshing = false;
  }
}

function onFile(event: Event) {
  const input = event.target as HTMLInputElement;
  file.value = input.files?.[0] ?? null;
}

async function submit() {
  if (submitting.value) return;
  error.value = "";
  if (mode.value === "upload" && !file.value) {
    error.value = "请选择视频或音频文件";
    return;
  }
  if (mode.value === "url" && !url.value.trim()) {
    error.value = "请填写视频直链";
    return;
  }
  if (mode.value === "url") {
    try {
      if (!["http:", "https:"].includes(new URL(url.value.trim()).protocol)) throw new Error();
    } catch {
      error.value = "请填写有效的 http 或 https 视频直链";
      return;
    }
  }
  submitting.value = true;
  uploadPercent.value = 0;
  try {
    const job =
      mode.value === "upload"
        ? await api.createTranscriptionUpload(file.value as File, language.value, title.value, (p) => {
            uploadPercent.value = p;
          })
        : await api.createTranscriptionUrl(url.value.trim(), language.value, title.value);
    title.value = "";
    url.value = "";
    file.value = null;
    if (fileInput.value) fileInput.value.value = "";
    await load();
    await select(job.id);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    submitting.value = false;
    uploadPercent.value = 0;
  }
}

async function copyText() {
  const text = detail.value?.text;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      if (!document.execCommand("copy")) throw new Error("复制失败，请手动选择文稿复制");
    } catch (e) {
      error.value = errorMessage(e);
      return;
    } finally {
      area.remove();
    }
  }
  copied.value = true;
  window.clearTimeout(copyTimer);
  copyTimer = window.setTimeout(() => (copied.value = false), 1500);
}

function download(format: "txt" | "srt") {
  if (!detail.value) return;
  const anchor = document.createElement("a");
  anchor.href = transcriptionFileUrl(detail.value.id, format);
  anchor.download = `transcript-${detail.value.id}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

async function remove(job: TranscriptionSummary) {
  if (removing.value !== null) return;
  if (!window.confirm(`确定删除转文稿「${job.title}」？文稿与源文件都会被清理。`)) return;
  removing.value = job.id;
  try {
    await api.deleteTranscription(job.id);
    if (selectedId === job.id) {
      detailRequest++;
      selectedId = null;
      detail.value = null;
    }
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    removing.value = null;
  }
}

onMounted(async () => {
  try {
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  }
  if (!disposed) timer = window.setInterval(() => busy.value && refresh(), 4000);
});
onUnmounted(() => {
  disposed = true;
  window.clearInterval(timer);
  window.clearTimeout(copyTimer);
});
</script>

<template>
  <div class="stack">
    <div class="row between">
      <div>
        <h1>视频转文稿</h1>
        <p class="muted">上传视频或粘贴可直接播放的视频直链，自动识别语音并生成文稿，方便复制为补充资料。</p>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="card stack">
      <div class="row">
        <button class="btn" :disabled="submitting" :class="{ primary: mode === 'upload' }" @click="mode = 'upload'">
          <Upload :size="14" /> 上传文件
        </button>
        <button class="btn" :disabled="submitting" :class="{ primary: mode === 'url' }" @click="mode = 'url'">
          <Link2 :size="14" /> 视频直链
        </button>
      </div>

      <div v-if="mode === 'upload'" class="field">
        <label>视频 / 音频文件</label>
        <input ref="fileInput" type="file" accept="video/*,audio/*" class="input" :disabled="submitting" @change="onFile" />
      </div>
      <div v-else class="field">
        <label>视频直链（http/https，打开即可播放）</label>
        <input v-model="url" class="input" placeholder="https://example.com/video.mp4" />
      </div>

      <div class="grid cols-2">
        <div class="field">
          <label>识别语言</label>
          <select v-model="language" class="input">
            <option value="zh">中文</option>
            <option value="en">英文</option>
            <option value="auto">自动检测</option>
          </select>
        </div>
        <div class="field">
          <label>标题（可空）</label>
          <input v-model="title" class="input" placeholder="默认取文件名或链接名" />
        </div>
      </div>

      <div v-if="submitting && uploadPercent > 0" class="progress">
        <span :style="{ width: uploadPercent + '%' }"></span>
      </div>
      <div class="row">
        <button class="btn primary" :disabled="submitting" @click="submit">
          <Loader2 v-if="submitting" :size="14" class="spin" />
          <FileText v-else :size="14" />
          {{ submitting ? "提交中…" : "开始转文稿" }}
        </button>
      </div>
    </div>

    <div class="card">
      <h2>转文稿记录</h2>
      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>标题</th>
            <th>来源</th>
            <th>状态</th>
            <th>时长</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="job in jobs"
            :key="job.id"
            :class="{ selected: detail?.id === job.id }"
            style="cursor: pointer"
            @click="select(job.id)"
          >
            <td>{{ job.title }}</td>
            <td class="muted">
              <span class="badge">{{ job.source_type === "url" ? "直链" : "上传" }}</span>
            </td>
            <td><span class="badge" :class="statusOf(job.status).cls">{{ statusOf(job.status).label }}</span></td>
            <td class="mono">{{ formatDuration(job.duration_sec) }}</td>
            <td class="muted">{{ formatDateTime(job.created_at) }}</td>
            <td style="text-align: right">
              <button class="btn sm danger" aria-label="删除文稿" :disabled="removing !== null" @click.stop="remove(job)"><Trash2 :size="13" /></button>
            </td>
          </tr>
          <tr v-if="!jobs.length">
            <td colspan="6" class="muted">暂无记录，上传视频或粘贴直链开始。</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>

    <div v-if="detail" class="card stack">
      <div class="row between">
        <div>
          <h2>{{ detail.title }}</h2>
          <p class="muted">
            {{ detail.source_type === "url" ? detail.source_ref : `文件：${detail.source_ref}` }} ·
            {{ formatDuration(detail.duration_sec) }} · {{ textLength }} 字
          </p>
        </div>
        <div class="row">
          <button class="btn" :disabled="!detail.text" @click="copyText">
            <Check v-if="copied" :size="14" />
            <Copy v-else :size="14" />
            {{ copied ? "已复制" : "复制文稿" }}
          </button>
          <button class="btn" :disabled="!detail.text" @click="download('txt')">
            <Download :size="14" /> TXT
          </button>
          <button class="btn" :disabled="!detail.text" @click="download('srt')">
            <Download :size="14" /> SRT
          </button>
        </div>
      </div>

      <p v-if="detail.status === 'failed'" class="error">{{ detail.error_message || "转文稿失败" }}</p>
      <p v-else-if="detail.status !== 'succeeded'" class="muted">
        {{ statusOf(detail.status).label }}，完成后这里会显示文稿。
      </p>
      <textarea
        v-if="detail.text"
        class="input transcript"
        readonly
        rows="18"
        :value="detail.text"
      ></textarea>
    </div>
  </div>
</template>

<style scoped>
.error {
  color: var(--err);
}
.transcript {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  line-height: 1.7;
}
tbody tr.selected {
  background: var(--accent-weak);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
