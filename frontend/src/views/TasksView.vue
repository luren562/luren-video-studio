<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { RotateCw } from "lucide-vue-next";
import { api, errorMessage } from "../api";
import type { PipelineEvent, PipelineTask } from "../types";
import { formatDateTime, taskStatus } from "../utils";

const tasks = ref<PipelineTask[]>([]);
const status = ref("");
const selected = ref<PipelineTask | null>(null);
const events = ref<PipelineEvent[]>([]);
const error = ref("");
const loading = ref(false);
const retrying = ref<number | null>(null);
let timer: number | undefined;
let disposed = false;
let requestId = 0;
let eventRequestId = 0;

async function loadEvents(id: number) {
  const request = ++eventRequestId;
  try {
    const result = await api.taskEvents(id);
    if (!disposed && request === eventRequestId && selected.value?.id === id) events.value = result;
  } catch (e) {
    if (!disposed && request === eventRequestId) error.value = errorMessage(e);
  }
}

async function load() {
  const request = ++requestId;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.tasks({ status: status.value || undefined, limit: 200 });
    if (disposed || request !== requestId) return;
    tasks.value = result;
    if (selected.value) {
      selected.value = tasks.value.find((t) => t.id === selected.value!.id) || null;
      if (selected.value) await loadEvents(selected.value.id);
      else {
        eventRequestId++;
        events.value = [];
      }
    }
  } catch (e) {
    if (!disposed && request === requestId) error.value = errorMessage(e);
  } finally {
    if (!disposed && request === requestId) loading.value = false;
  }
}

async function open(task: PipelineTask) {
  selected.value = task;
  events.value = [];
  error.value = "";
  await loadEvents(task.id);
}

async function retry(id: number) {
  if (retrying.value !== null) return;
  retrying.value = id;
  error.value = "";
  try {
    await api.retryTask(id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    retrying.value = null;
  }
}

watch(status, load);
onMounted(() => {
  load();
  timer = window.setInterval(() => { if (!loading.value) void load(); }, 4000);
});
onUnmounted(() => {
  disposed = true;
  window.clearInterval(timer);
});
</script>

<template>
  <div class="stack">
    <div class="row between">
      <h1>任务中心</h1>
      <select v-model="status" class="input" style="max-width: 160px">
        <option value="">全部状态</option>
        <option value="queued">排队中</option>
        <option value="running">执行中</option>
        <option value="succeeded">成功</option>
        <option value="failed">失败</option>
        <option value="cancelled">已取消</option>
      </select>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="grid cols-2">
      <div class="card">
        <div class="table-scroll">
      <table>
          <thead>
            <tr>
              <th>#</th>
              <th>类型</th>
              <th>状态</th>
              <th>尝试</th>
              <th>创建</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tasks" :key="t.id" @click="open(t)" style="cursor: pointer">
              <td class="mono">{{ t.id }}</td>
              <td>{{ t.kind }}</td>
              <td><span class="badge" :class="taskStatus(t.status).cls">{{ taskStatus(t.status).label }}</span></td>
              <td class="mono">{{ t.attempts }}/{{ t.max_attempts }}</td>
              <td class="muted mono">{{ formatDateTime(t.created_at) }}</td>
              <td style="text-align: right">
                <button
                  v-if="t.status === 'failed' || t.status === 'cancelled'"
                  class="btn sm"
                  :disabled="retrying !== null"
                  @click.stop="retry(t.id)"
                >
                  <RotateCw :size="13" /> 重试
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
        <p v-if="!tasks.length && !error" class="muted">{{ loading ? '正在加载任务…' : '暂无符合条件的任务。' }}</p>
      </div>

      <div class="card">
        <h2>任务详情</h2>
        <div v-if="selected">
          <div class="row between">
            <strong>#{{ selected.id }} {{ selected.kind }}</strong>
            <span class="badge" :class="taskStatus(selected.status).cls">{{ taskStatus(selected.status).label }}</span>
          </div>
          <p v-if="selected.error_message" class="error">
            {{ selected.error_code }}：{{ selected.error_message }}
          </p>
          <div class="log">
            <div v-for="e in events" :key="e.id" class="log-line">
              <span class="muted mono">{{ formatDateTime(e.created_at) }}</span>
              <span class="badge" :class="e.level === 'error' ? 'err' : e.level === 'warning' ? 'warn' : ''">{{ e.level }}</span>
              <span>{{ e.message }}</span>
            </div>
          </div>
        </div>
        <p v-else class="muted">点击左侧任务查看事件流。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error {
  color: var(--err);
}
.log {
  margin-top: 10px;
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.log-line {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
}
</style>
