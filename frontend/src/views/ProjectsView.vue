<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { Trash2, RotateCw } from "lucide-vue-next";
import { api, errorMessage } from "../api";
import type { VideoProject } from "../types";
import { formatDateTime, formatDuration, projectStatus } from "../utils";

const projects = ref<VideoProject[]>([]);
const status = ref("");
const keyword = ref("");
const loading = ref(false);
const error = ref("");
const removing = ref<number | null>(null);
let requestId = 0;

async function load() {
  const request = ++requestId;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.projects({
      status: status.value || undefined,
      keyword: keyword.value.trim() || undefined,
    });
    if (request === requestId) projects.value = result;
  } catch (e) {
    if (request === requestId) error.value = errorMessage(e);
  } finally {
    if (request === requestId) loading.value = false;
  }
}

let debounce: number | undefined;
watch(keyword, () => {
  requestId++;
  window.clearTimeout(debounce);
  debounce = window.setTimeout(load, 300);
});
watch(status, load);

async function remove(id: number) {
  if (removing.value !== null) return;
  if (!confirm("确认删除该项目？此操作不可恢复。")) return;
  removing.value = id;
  error.value = "";
  try {
    await api.deleteProject(id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    removing.value = null;
  }
}

onMounted(load);
onUnmounted(() => {
  requestId++;
  window.clearTimeout(debounce);
});
</script>

<template>
  <div class="stack">
    <div class="row between">
      <h1>需求工作台</h1>
      <router-link :to="{ name: 'project-create' }" class="btn primary">新建需求</router-link>
    </div>

    <div class="card">
      <div class="row wrap">
        <input v-model="keyword" class="input" style="max-width: 260px" placeholder="搜索主题 / 标题" />
        <select v-model="status" class="input" style="max-width: 160px">
          <option value="">全部状态</option>
          <option value="generating">生成中</option>
          <option value="spec_ready">待渲染</option>
          <option value="pending_review">待审核</option>
          <option value="approved">已批准</option>
          <option value="rendering">渲染中</option>
          <option value="rendered">已渲染</option>
          <option value="completed">已入库</option>
          <option value="failed">失败</option>
          <option value="needs_attention">需处理</option>
        </select>
      </div>

      <p v-if="error" class="error">{{ error }}</p>

      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>主题</th>
            <th>状态</th>
            <th>时长</th>
            <th>版本</th>
            <th>更新时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="p.id">
            <td>
              <router-link :to="{ name: 'project-detail', params: { id: p.id } }">
                {{ p.title || p.topic || `项目 #${p.id}` }}
              </router-link>
            </td>
            <td>
              <span class="badge" :class="projectStatus(p.status).cls">
                {{ projectStatus(p.status).label }}
              </span>
            </td>
            <td class="mono">{{ formatDuration(p.duration_target_sec) }}</td>
            <td class="muted">{{ p.current_version_id ? `#${p.current_version_id}` : "尚未生成" }}</td>
            <td class="muted mono">{{ formatDateTime(p.updated_at) }}</td>
            <td class="row" style="justify-content: flex-end">
              <router-link
                :to="{ name: 'project-detail', params: { id: p.id } }"
                class="btn sm"
                title="打开"
              >
                <RotateCw :size="13" /> 打开
              </router-link>
              <button class="btn sm danger" title="删除" aria-label="删除项目" :disabled="removing !== null" @click="remove(p.id)">
                <Trash2 :size="13" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <p v-if="loading" class="muted" role="status">正在加载项目…</p>
      <p v-else-if="!projects.length && !error" class="muted">{{ keyword || status ? '没有符合筛选条件的项目。' : '暂无项目，点击右上角创建第一个需求。' }}</p>
    </div>
  </div>
</template>

<style scoped>
table {
  margin-top: 12px;
}
.error {
  color: var(--err);
}
</style>
