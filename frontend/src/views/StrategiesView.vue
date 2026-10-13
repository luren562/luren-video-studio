<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Plus, Sparkles, Star, Trash2 } from "lucide-vue-next";
import { api, errorMessage } from "../api";
import type { ContentStrategy, StrategyPayload } from "../types";

interface StrategyForm {
  name: string;
  description: string;
  audience: string;
  tone: string;
  content_goal: string;
  prompt_rules: string;
  banned: string;
  style_guide_md: string;
  is_active: boolean;
}

function emptyForm(): StrategyForm {
  return {
    name: "",
    description: "",
    audience: "",
    tone: "",
    content_goal: "",
    prompt_rules: "",
    banned: "",
    style_guide_md: "",
    is_active: true,
  };
}

const strategies = ref<ContentStrategy[]>([]);
const error = ref("");
const saving = ref(false);
const showNew = ref(false);
const draft = ref<StrategyForm>(emptyForm());
const editingId = ref<number | null>(null);
const edit = ref<StrategyForm>(emptyForm());

function splitBanned(text: string): string[] {
  return [...new Set(text.split(/[\n,，、]+/).map((item) => item.trim()).filter(Boolean))];
}

function toPayload(form: StrategyForm): StrategyPayload {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    audience: form.audience.trim(),
    tone: form.tone.trim(),
    content_goal: form.content_goal.trim(),
    prompt_rules: form.prompt_rules.trim(),
    banned_phrases: splitBanned(form.banned),
    style_guide_md: form.style_guide_md,
    is_active: form.is_active,
  };
}

function fromStrategy(strategy: ContentStrategy): StrategyForm {
  return {
    name: strategy.name,
    description: strategy.description,
    audience: strategy.audience,
    tone: strategy.tone,
    content_goal: strategy.content_goal,
    prompt_rules: strategy.prompt_rules,
    banned: (strategy.banned_phrases_json || []).join("\n"),
    style_guide_md: strategy.style_guide_md,
    is_active: strategy.is_active,
  };
}

async function load() {
  strategies.value = await api.strategies();
}

async function create() {
  if (saving.value) return;
  error.value = "";
  if (!draft.value.name.trim()) {
    error.value = "请填写策略名称";
    return;
  }
  saving.value = true;
  try {
    await api.createStrategy(toPayload(draft.value));
    showNew.value = false;
    draft.value = emptyForm();
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

function beginEdit(strategy: ContentStrategy) {
  error.value = "";
  editingId.value = strategy.id;
  edit.value = fromStrategy(strategy);
}

async function saveEdit() {
  if (saving.value) return;
  if (editingId.value === null) return;
  error.value = "";
  if (!edit.value.name.trim()) {
    error.value = "请填写策略名称";
    return;
  }
  saving.value = true;
  try {
    await api.updateStrategy(editingId.value, toPayload(edit.value));
    editingId.value = null;
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function cloneStrategy(strategy: ContentStrategy) {
  if (saving.value) return;
  error.value = "";
  saving.value = true;
  try {
    const form = fromStrategy(strategy);
    form.name = `${strategy.name} · 副本`;
    await api.createStrategy(toPayload(form));
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function setDefault(id: number) {
  if (saving.value) return;
  error.value = "";
  saving.value = true;
  try {
    await api.setDefaultStrategy(id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function remove(strategy: ContentStrategy) {
  if (saving.value) return;
  if (!window.confirm(`确定删除创作策略「${strategy.name}」？关联项目将解除绑定。`)) return;
  error.value = "";
  saving.value = true;
  try {
    await api.deleteStrategy(strategy.id);
    if (editingId.value === strategy.id) editingId.value = null;
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  }
});
</script>

<template>
  <div class="stack">
    <div class="row between">
      <div>
        <h1>创作策略</h1>
        <p class="muted">定义受众、语气与内容规则，让每一支视频都保持一致的创作风格。</p>
      </div>
      <button :disabled="saving" class="btn primary" @click="showNew = !showNew">
        <Plus :size="14" /> 新建策略
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="showNew" class="card stack">
      <div class="row">
        <Sparkles :size="16" />
        <h2>新建创作策略</h2>
      </div>
      <div class="grid cols-2">
        <div class="field">
          <label>名称</label>
          <input v-model="draft.name" class="input" placeholder="如：光宇 · 数学拆解人生" />
        </div>
        <div class="field">
          <label>目标受众</label>
          <input v-model="draft.audience" class="input" placeholder="对认知成长感兴趣的人" />
        </div>
      </div>
      <div class="field">
        <label>简介</label>
        <input v-model="draft.description" class="input" />
      </div>
      <div class="grid cols-2">
        <div class="field">
          <label>语气</label>
          <textarea v-model="draft.tone" class="input" rows="3"></textarea>
        </div>
        <div class="field">
          <label>内容目标</label>
          <textarea v-model="draft.content_goal" class="input" rows="3"></textarea>
        </div>
      </div>
      <div class="field">
        <label>结构 / 写法规则</label>
        <textarea v-model="draft.prompt_rules" class="input" rows="4"></textarea>
      </div>
      <div class="field">
        <label>禁用表达（每行一个，或用逗号分隔）</label>
        <textarea v-model="draft.banned" class="input" rows="3"></textarea>
      </div>
      <div class="field">
        <label>风格画像全文（Markdown）</label>
        <textarea v-model="draft.style_guide_md" class="input" rows="10"></textarea>
      </div>
      <label class="row check">
        <input v-model="draft.is_active" type="checkbox" /> 启用
      </label>
      <div class="row">
        <button :disabled="saving" class="btn primary" @click="create">保存</button>
        <button :disabled="saving" class="btn" @click="showNew = false">取消</button>
      </div>
    </div>

    <div class="card">
      <h2>已有策略</h2>
      <p class="muted">设为默认的策略会在新建需求时自动选中。</p>
      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>受众</th>
            <th>禁用词</th>
            <th>风格全文</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in strategies" :key="s.id">
            <td>
              {{ s.name }}
              <span v-if="s.is_default" class="badge ok" style="margin-left: 6px">默认</span>
              <span v-if="!s.is_active" class="badge" style="margin-left: 6px">停用</span>
            </td>
            <td class="muted">{{ s.audience || "—" }}</td>
            <td class="mono">{{ (s.banned_phrases_json || []).length }}</td>
            <td class="muted">{{ s.style_guide_md ? "已填写" : "—" }}</td>
            <td style="text-align: right">
              <button :disabled="saving" class="btn sm" @click="beginEdit(s)">编辑</button>
              <button :disabled="saving" class="btn sm" @click="cloneStrategy(s)">复制</button>
              <button :disabled="saving" v-if="!s.is_default" class="btn sm" @click="setDefault(s.id)">
                <Star :size="13" /> 设为默认
              </button>
              <button :disabled="saving" class="btn sm danger" @click="remove(s)">
                <Trash2 :size="13" />
              </button>
            </td>
          </tr>
          <tr v-if="!strategies.length">
            <td colspan="5" class="muted">暂无策略，点击右上角新建。</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>

    <div v-if="editingId !== null" class="card stack">
      <h2>编辑创作策略</h2>
      <div class="grid cols-2">
        <div class="field">
          <label>名称</label>
          <input v-model="edit.name" class="input" />
        </div>
        <div class="field">
          <label>目标受众</label>
          <input v-model="edit.audience" class="input" />
        </div>
      </div>
      <div class="field">
        <label>简介</label>
        <input v-model="edit.description" class="input" />
      </div>
      <div class="grid cols-2">
        <div class="field">
          <label>语气</label>
          <textarea v-model="edit.tone" class="input" rows="3"></textarea>
        </div>
        <div class="field">
          <label>内容目标</label>
          <textarea v-model="edit.content_goal" class="input" rows="3"></textarea>
        </div>
      </div>
      <div class="field">
        <label>结构 / 写法规则</label>
        <textarea v-model="edit.prompt_rules" class="input" rows="4"></textarea>
      </div>
      <div class="field">
        <label>禁用表达（每行一个，或用逗号分隔）</label>
        <textarea v-model="edit.banned" class="input" rows="3"></textarea>
      </div>
      <div class="field">
        <label>风格画像全文（Markdown）</label>
        <textarea v-model="edit.style_guide_md" class="input" rows="10"></textarea>
      </div>
      <label class="row check">
        <input v-model="edit.is_active" type="checkbox" /> 启用
      </label>
      <div class="row">
        <button :disabled="saving" class="btn primary" @click="saveEdit">保存策略</button>
        <button :disabled="saving" class="btn" @click="editingId = null">取消</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error {
  color: var(--err);
}
.check {
  font-size: 13px;
  color: var(--text-muted);
}
</style>
