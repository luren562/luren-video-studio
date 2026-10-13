<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Star } from "lucide-vue-next";
import { api, errorMessage } from "../api";
import type { Engine, VideoStyle } from "../types";
import { engineLabel } from "../utils";

const engines = ref<Engine[]>([]);
const styles = ref<VideoStyle[]>([]);
const error = ref("");
const saving = ref(false);
const showNew = ref(false);
const draft = ref({ name: "", engine: "shotcraft", aspect: "16:9", lang: "zh", default_duration_sec: 45 });
const editingId = ref<number | null>(null);
const editName = ref("");
const editDescription = ref("");
const editTheme = ref<Record<string, string>>({});
const editSkill = ref("video-shotcraft");
const editProfile = ref("ivory");

function beginEdit(style: VideoStyle) {
  editingId.value = style.id;
  editName.value = style.name;
  editDescription.value = String(style.engine_config_json.description || "");
  editSkill.value = String(style.engine_config_json.skill_id || "video-shotcraft");
  editProfile.value = String(style.engine_config_json.visual_profile || "ivory");
  editTheme.value = Object.fromEntries(Object.entries(style.theme_json).filter((item): item is [string, string] => typeof item[1] === "string"));
}

async function saveEdit() {
  if (saving.value) return;
  const style = styles.value.find((item) => item.id === editingId.value);
  if (!style) return;
  error.value = "";
  if (!editName.value.trim()) {
    error.value = "请填写风格名称";
    return;
  }
  saving.value = true;
  try {
    await api.updateStyle(style.id, {
      name: editName.value.trim(),
      theme_json: { ...style.theme_json, ...editTheme.value },
      engine_config_json: { ...style.engine_config_json, description: editDescription.value.trim(),
        skill_id: editSkill.value, visual_profile: editSkill.value === "video-diagram-explainer" ? editProfile.value : null },
    });
    editingId.value = null;
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function cloneStyle(style: VideoStyle) {
  if (saving.value) return;
  error.value = "";
  saving.value = true;
  try {
    const created = await api.createStyle({
      name: `${style.name} · 副本 ${Date.now().toString().slice(-4)}`,
      engine: style.engine,
      aspect: style.aspect,
      lang: style.lang,
      default_duration_sec: style.default_duration_sec,
      theme_json: { ...style.theme_json },
      engine_config_json: { ...style.engine_config_json },
      is_active: true,
    });
    await load();
    beginEdit(created);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function load() {
  engines.value = await api.engines();
  styles.value = await api.styles();
}

async function create() {
  if (saving.value) return;
  error.value = "";
  if (!draft.value.name.trim()) {
    error.value = "请填写风格名称";
    return;
  }
  if (!Number.isInteger(draft.value.default_duration_sec) || draft.value.default_duration_sec <= 0) {
    error.value = "默认时长请输入大于 0 的整数秒";
    return;
  }
  saving.value = true;
  try {
    await api.createStyle({ ...draft.value, name: draft.value.name.trim() });
    showNew.value = false;
    draft.value = { name: "", engine: "shotcraft", aspect: "16:9", lang: "zh", default_duration_sec: 45 };
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
    await api.setDefaultStyle(id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try { await load(); } catch (e) { error.value = errorMessage(e); }
});
</script>

<template>
  <div class="stack">
    <div class="row between">
      <h1>风格档</h1>
      <button :disabled="saving" class="btn primary" @click="showNew = !showNew">新建风格档</button>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="card">
      <h2>引擎能力</h2>
      <div class="grid cols-3" style="margin-top: 10px">
        <div v-for="e in engines" :key="e.key" class="engine">
          <div class="row between">
            <strong>{{ e.display_name }}</strong>
            <span class="badge">{{ e.aspect }}</span>
          </div>
          <p class="muted">{{ e.description }}</p>
          <div class="row wrap">
            <span v-if="e.needs_voiceover" class="badge info">需配音</span>
            <span v-if="e.needs_assets" class="badge info">需素材</span>
            <span v-if="e.needs_review_agent" class="badge warn">需独立审片</span>
          </div>
          <div class="muted small">质检闸：{{ Object.keys(e.gates).join(" · ") || "无脚本闸" }}</div>
        </div>
      </div>
    </div>

    <div v-if="showNew" class="card stack">
      <h2>新建风格档</h2>
      <div class="grid cols-2">
        <div class="field">
          <label>名称</label>
          <input v-model="draft.name" class="input" />
        </div>
        <div class="field">
          <label>引擎</label>
          <select v-model="draft.engine" class="input">
            <option v-for="e in engines" :key="e.key" :value="e.key">{{ e.display_name }}</option>
          </select>
        </div>
        <div class="field">
          <label>画幅</label>
          <select v-model="draft.aspect" class="input">
            <option value="16:9">16:9 横屏</option>
            <option value="9:16">9:16 竖屏</option>
          </select>
        </div>
        <div class="field">
          <label>默认时长（秒）</label>
          <input v-model.number="draft.default_duration_sec" type="number" class="input" />
        </div>
      </div>
      <div class="row">
        <button :disabled="saving" class="btn primary" @click="create">保存</button>
      </div>
    </div>

    <div class="card">
      <h2>已有风格档</h2>
      <p class="muted">风格档决定片子的调性与默认参数。可复制风格档后调整配色。</p>
      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>引擎</th>
            <th>画幅</th>
            <th>语言</th>
            <th>默认时长</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in styles" :key="s.id">
            <td>
              {{ s.name }}
              <span v-if="s.is_default" class="badge ok" style="margin-left: 6px">默认</span>
            </td>
            <td>{{ s.engine_config_json.skill_id === 'video-diagram-explainer' ? '科普图解 · Agent 精修' : engineLabel(s.engine) }}</td>
            <td>{{ s.aspect }}</td>
            <td>{{ s.lang === "zh" ? "中文" : "EN" }}</td>
            <td class="mono">{{ s.default_duration_sec }}s</td>
            <td style="text-align: right">
              <button :disabled="saving" class="btn sm" @click="beginEdit(s)">编辑</button>
              <button :disabled="saving" class="btn sm" @click="cloneStyle(s)">复制</button>
              <button :disabled="saving" v-if="!s.is_default" class="btn sm" @click="setDefault(s.id)">
                <Star :size="13" /> 设为默认
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
    <div v-if="editingId !== null" class="card stack">
      <h2>编辑风格档</h2>
      <div class="field"><label>名称</label><input v-model="editName" class="input" /></div>
      <div class="field"><label>简介</label><input v-model="editDescription" class="input" /></div>
      <div class="grid cols-2">
        <div class="field"><label>视频制作方法</label>
          <select v-model="editSkill" class="input">
            <option value="video-shotcraft">电影感产品视频</option>
            <option value="video-diagram-explainer">科普图解视频</option>
            <option value="video-talkcraft">口播观点视频</option>
          </select>
        </div>
        <div v-if="editSkill === 'video-diagram-explainer'" class="field"><label>视觉预设</label>
          <select v-model="editProfile" class="input">
            <option value="ivory">米白极简</option><option value="midnight">深色技术</option><option value="paper">清晰教材</option>
          </select>
        </div>
      </div>
      <div class="grid cols-3">
        <div v-for="key in ['bg', 'fg', 'accent']" :key="key" class="field">
          <label>{{ key }}</label><input v-model="editTheme[key]" type="color" class="input color-input" />
        </div>
      </div>
      <div class="row"><button :disabled="saving" class="btn primary" @click="saveEdit">保存风格</button><button :disabled="saving" class="btn" @click="editingId = null">取消</button></div>
    </div>
  </div>
</template>

<style scoped>
.engine {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.engine p {
  margin: 0;
  font-size: 13px;
}
.small {
  font-size: 12px;
}
.error {
  color: var(--err);
}
.color-input { min-height: 42px; padding: 4px; }
</style>
