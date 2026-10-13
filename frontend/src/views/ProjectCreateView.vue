<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, errorMessage } from "../api";
import type { AIModel, ContentStrategy, TtsVoice, VideoStyle } from "../types";
import { engineLabel } from "../utils";

const router = useRouter();
const styles = ref<VideoStyle[]>([]);
const strategies = ref<ContentStrategy[]>([]);
const models = ref<AIModel[]>([]);
const error = ref("");
const submitting = ref(false);
const voices = ref<TtsVoice[]>([]);
const voicesError = ref("");
const voicesLoading = ref(false);
const previewLoading = ref(false);
const previewUrl = ref("");
const audioError = ref("");
const uploadBusy = ref(false);
const uploadedName = ref("");
let previewRequest = 0;

const form = ref({
  topic: "",
  title: "",
  audience: "",
  goal: "",
  source_notes: "",
  constraints: "",
  reference_url: "",
  style_id: null as number | null,
  strategy_id: null as number | null,
  model_id: null as number | null,
  duration_target_sec: 45,
  lang: "zh",
  review_required: true,
  theme_json: { accent: "#FFFFFF" },
  bgm_enabled: true,
  tts_enabled: true,
  tts_voice: null as string | null,
  tts_rate: null as number | null,
  tts_asset_id: null as number | null,
});

const selectedVoice = computed(() => voices.value.find(v => v.id === form.value.tts_voice));
const freeVoices = computed(() => voices.value);
const rateLabel = computed(() => {
  const r = form.value.tts_rate;
  if (r === null || r === undefined) return "默认（跟随后台设置）";
  return r > 0 ? `+${r}%` : `${r}%`;
});

function toggleRate(event: Event) {
  form.value.tts_rate = (event.target as HTMLInputElement).checked ? 0 : null;
}

function clearPreview() {
  previewRequest++;
  previewLoading.value = false;
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = "";
  audioError.value = "";
}
watch(() => [form.value.tts_voice, form.value.tts_rate, form.value.tts_enabled, form.value.tts_asset_id], clearPreview);
onUnmounted(clearPreview);

async function loadVoices() {
  voicesLoading.value = true;
  voicesError.value = "";
  try {
    voices.value = await api.ttsVoices();
    form.value.tts_voice = (voices.value.find(v => v.is_default) || voices.value[0])?.id ?? null;
  } catch (e) {
    voicesError.value = errorMessage(e);
  } finally {
    voicesLoading.value = false;
  }
}

async function previewVoice() {
  if (!form.value.tts_voice) return;
  clearPreview();
  const request = previewRequest;
  previewLoading.value = true;
  try {
    const blob = await api.previewVoice(form.value.tts_voice, form.value.tts_rate);
    if (request === previewRequest) previewUrl.value = URL.createObjectURL(blob);
  } catch (e) {
    if (request === previewRequest) audioError.value = errorMessage(e);
  } finally {
    if (request === previewRequest) previewLoading.value = false;
  }
}

async function uploadNarration(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || uploadBusy.value) return;
  uploadBusy.value = true;
  audioError.value = "";
  try {
    const asset = await api.uploadNarration(file);
    form.value.tts_asset_id = asset.id;
    uploadedName.value = asset.filename;
  } catch (e) {
    audioError.value = errorMessage(e);
  } finally {
    uploadBusy.value = false;
    input.value = "";
  }
}

function pickStyle(style: VideoStyle) {
  form.value.style_id = style.id;
  form.value.duration_target_sec = style.default_duration_sec;
  form.value.lang = style.lang;
  const accent = style.theme_json.accent;
  form.value.theme_json.accent = typeof accent === "string" && /^#[0-9a-fA-F]{6}$/.test(accent) ? accent : "#FFFFFF";
  form.value.bgm_enabled = style.engine_config_json.bgm === "required";
}

onMounted(async () => {
  void loadVoices();
  try {
    const [styleList, strategyList, modelList] = await Promise.all([
      api.styles(),
      api.strategies(true).catch(() => [] as ContentStrategy[]),
      api.models(),
    ]);
    styles.value = styleList.filter(s => s.is_active);
    strategies.value = strategyList;
    models.value = modelList.filter((m) => ["text", "agent", "vision"].includes(m.capability) && m.is_active);
    const def = styles.value.find((s) => s.is_default) || styles.value[0];
    if (def) pickStyle(def);
    form.value.strategy_id = (strategies.value.find((s) => s.is_default) || strategies.value[0])?.id ?? null;
  } catch (e) {
    error.value = errorMessage(e);
  }
});

async function submit() {
  if (submitting.value || uploadBusy.value) return;
  if (!form.value.topic.trim()) {
    error.value = "请填写主题";
    return;
  }
  if (!form.value.style_id) {
    error.value = "请先选择一个可用的风格档";
    return;
  }
  if (!Number.isInteger(form.value.duration_target_sec) || form.value.duration_target_sec <= 0) {
    error.value = "目标时长请输入大于 0 的整数秒";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    const project = await api.createProject({ ...form.value, topic: form.value.topic.trim() });
    await router.push({ name: "project-detail", params: { id: project.id } });
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="stack" style="max-width: 900px">
    <div class="row between">
      <h1>新建需求</h1>
      <router-link :to="{ name: 'projects' }" class="muted">返回列表</router-link>
    </div>

    <div class="card stack">
      <div class="field">
        <label>主题（必填）</label>
        <input v-model="form.topic" class="input" placeholder="例如：为什么天空是蓝色的" />
      </div>
      <div class="grid cols-2">
        <div class="field">
          <label>标题（可选）</label>
          <input v-model="form.title" class="input" />
        </div>
        <div class="field">
          <label>目标受众</label>
          <input v-model="form.audience" class="input" placeholder="例如：对科普感兴趣的普通观众" />
        </div>
      </div>
      <div class="field">
        <label>内容目标</label>
        <input v-model="form.goal" class="input" placeholder="例如：用 2 分钟讲清瑞利散射" />
      </div>
      <div class="grid cols-2">
        <div class="field">
          <label>补充事实 / 参考资料</label>
          <textarea v-model="form.source_notes" class="input" placeholder="可贴要点或链接；画面中出现的数字必须有来源" />
        </div>
        <div class="field">
          <label>必须包含 / 禁止出现</label>
          <textarea v-model="form.constraints" class="input" />
        </div>
      </div>
      <div class="field">
        <label>参考网址（可选）</label>
        <input v-model="form.reference_url" class="input" />
      </div>
    </div>

    <div class="card stack">
      <h2>风格与参数</h2>
      <div class="style-grid">
        <button
          v-for="s in styles"
          :key="s.id"
          type="button"
          class="style-card"
          :class="{ active: s.id === form.style_id }"
          @click="pickStyle(s)"
        >
          <div class="row between">
            <strong>{{ s.name }}</strong>
            <span class="badge">{{ s.engine_config_json.skill_id === 'video-diagram-explainer' ? '科普图解' : engineLabel(s.engine) }}</span>
          </div>
          <div class="muted">{{ s.aspect }} · {{ s.lang === "zh" ? "中文" : "English" }} · 默认 {{ s.default_duration_sec }}s</div>
        </button>
      </div>

      <div class="grid cols-2">
        <div class="field">
          <label>目标时长（秒，大概即可）</label>
          <input v-model.number="form.duration_target_sec" type="number" class="input" min="15" />
        </div>
        <div class="field">
          <label>语言</label>
          <select v-model="form.lang" class="input">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>

      <div class="field" v-if="models.length">
        <label>制作模型（留空用默认）</label>
        <select v-model="form.model_id" class="input">
          <option :value="null">默认（风格/环境配置）</option>
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}（{{ m.model_id }}）</option>
        </select>
      </div>

      <div class="field" v-if="strategies.length">
        <label>创作策略（作者风格画像）</label>
        <select v-model="form.strategy_id" class="input">
          <option :value="null">不使用（按风格档默认）</option>
          <option v-for="s in strategies" :key="s.id" :value="s.id">
            {{ s.name }}{{ s.description ? ` · ${s.description}` : "" }}
          </option>
        </select>
        <small class="muted">策略会被注入口播脚本与画面制作，约束语气、结构与禁用表达。</small>
      </div>

      <div class="field">
        <label for="accent">视频主题色</label>
        <div class="row">
          <input id="accent" v-model="form.theme_json.accent" type="color" class="color-input" />
          <span>{{ form.theme_json.accent.toUpperCase() }}</span>
          <small class="muted">背景和文字颜色沿用所选风格</small>
        </div>
      </div>

      <label class="check-row">
        <input type="checkbox" v-model="form.bgm_enabled" />
        <span>配背景音乐（BGM）<small class="muted">关闭后仍保留音效和已开启的旁白</small></span>
      </label>

      <label class="check-row">
        <input type="checkbox" v-model="form.tts_enabled" />
        <span>中文配音<small class="muted">根据旁白脚本生成语音和同步字幕</small></span>
      </label>

      <div v-if="form.tts_enabled" class="stack narration-options">
        <div class="field">
          <label for="voice">中文音色</label>
          <div class="row">
            <select id="voice" v-model="form.tts_voice" class="input" :disabled="voicesLoading || !!form.tts_asset_id">
              <option :value="null">{{ voicesLoading ? '正在加载音色…' : '使用平台默认音色' }}</option>
              <optgroup v-if="freeVoices.length" label="音色（Edge · 免费，免登录）">
                <option v-for="v in freeVoices" :key="v.id" :value="v.id">
                  {{ v.localName }} · {{ v.gender.toLowerCase() === 'female' ? '女声' : '男声' }} · {{ v.locale }}
                </option>
              </optgroup>
            </select>
            <button type="button" class="btn" :disabled="!form.tts_voice || previewLoading || !!form.tts_asset_id" @click="previewVoice">
              {{ previewLoading ? '生成试听中…' : '试听' }}
            </button>
          </div>
          <small v-if="selectedVoice" class="muted">
            Edge 免费可用 · {{ selectedVoice.localName }}
          </small>
          <p v-if="voicesError" class="error">音色加载失败：{{ voicesError }} <button type="button" class="btn" @click="loadVoices">重试</button></p>
          <audio v-if="previewUrl" :src="previewUrl" controls autoplay @error="audioError = '试听播放失败，请重试'" />
        </div>
        <div class="field">
          <label>语速</label>
          <label class="check-row">
            <input type="checkbox" :checked="form.tts_rate !== null" @change="toggleRate" />
            <span>自定义语速<small class="muted">不勾选则跟随后台默认语速</small></span>
          </label>
          <div v-if="form.tts_rate !== null" class="row" style="align-items: center; gap: 10px">
            <input type="range" min="-50" max="50" step="5" v-model.number="form.tts_rate" style="flex: 1" />
            <span class="mono" style="min-width: 52px; text-align: right">{{ rateLabel }}</span>
          </div>
          <small class="muted">当前：{{ rateLabel }}（负值更慢、正值更快）</small>
        </div>
        <div class="field">
          <label for="manual-narration">或上传自己的中文旁白（可选）</label>
          <input id="manual-narration" type="file" accept="audio/*" :disabled="uploadBusy" @change="uploadNarration" />
          <small class="muted">上传后使用此音频配字幕；请在参考资料中附上对应文本。</small>
          <span v-if="uploadBusy" class="muted">正在上传…</span>
          <div v-if="form.tts_asset_id" class="row">
            <span>{{ uploadedName }}</span>
            <button type="button" class="btn" @click="form.tts_asset_id = null; uploadedName = ''">移除旁白选择</button>
          </div>
        </div>
        <p v-if="audioError" class="error" role="alert">{{ audioError }}</p>
      </div>

      <label class="check-row">
        <input type="checkbox" v-model="form.review_required" />
        <span>需要视觉审片<small class="muted">（勾选后 agent 抽帧自审画面；取消勾选将跳过抽帧自审与终审，更快但质量不另行把关）</small></span>
      </label>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <div class="row submit-row">
      <button class="btn primary" :disabled="submitting || uploadBusy" @click="submit">
        {{ submitting ? "提交中…" : "开始制作视频" }}
      </button>
      <span class="muted">后台由 agent 完成分镜、配音、画面与自审；成功渲染的成片会及时保存。</span>
    </div>
  </div>
</template>

<style scoped>
.style-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.color-input { width: 64px; height: 38px; padding: 3px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); cursor: pointer; }
.narration-options { padding: 16px; border: 1px solid var(--border); border-radius: var(--radius-sm); }
.narration-options select { flex: 1; min-width: 0; }
.narration-options audio { max-width: 100%; }
.style-card .badge { flex-shrink: 0; white-space: nowrap; }
.submit-row { flex-wrap: wrap; }
.submit-row .btn { white-space: nowrap; flex-shrink: 0; }
.submit-row > span { flex: 1 1 280px; }
@media (max-width: 600px) { .style-grid { grid-template-columns: 1fr; } }
.style-card {
  text-align: left;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.style-card.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-weak);
}
.error {
  color: var(--err);
}
.check-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  cursor: pointer;
  font-size: 14px;
}
.check-row small {
  display: block;
  font-weight: 400;
}
.style-mini-preview { width: 100%; aspect-ratio: 16/9; object-fit: cover; border-radius: 5px; margin: 7px 0; }
</style>
