<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Plus, PlugZap, Trash2 } from "lucide-vue-next";
import { api, errorMessage } from "../api";
import type { AIModel, AIProvider } from "../types";

const providers = ref<AIProvider[]>([]);
const models = ref<AIModel[]>([]);
const error = ref("");
const notice = ref("");
const catalogBusy = ref(false);

const pForm = ref({ name: "", base_url: "", api_key: "", default_model_id: "" });
const mForm = ref({ provider_id: null as number | null, name: "", model_id: "", capability: "text" });
const modelCapabilities = ["text", "agent", "vision", "image", "tts", "asr"];

const renderConcurrency = ref(1);
const ttsRate = ref(0);
const savingSettings = ref(false);

const cover = ref({ base_url: "", has_api_key: false, model: "", size: "" });
const coverApiKey = ref("");
const coverBusy = ref(false);
const coverMsg = ref("");

async function loadCover() {
  try {
    cover.value = await api.coverConfig();
  } catch (e) {
    coverMsg.value = errorMessage(e);
  }
}

async function saveCover() {
  if (coverBusy.value) return;
  coverBusy.value = true;
  coverMsg.value = "";
  try {
    cover.value = await api.saveCoverConfig({
      base_url: cover.value.base_url.trim(),
      model: cover.value.model.trim(),
      size: cover.value.size.trim(),
      api_key: coverApiKey.value,
    });
    coverApiKey.value = "";
    coverMsg.value = "已保存";
  } catch (e) {
    coverMsg.value = errorMessage(e);
  } finally {
    coverBusy.value = false;
  }
}

async function testCover() {
  if (coverBusy.value) return;
  coverBusy.value = true;
  coverMsg.value = "测试生图中…";
  try {
    const r = await api.testCoverConfig();
    coverMsg.value = r.ok ? `连通正常（模型 ${r.model}，${r.latency_ms}ms）` : "测试失败";
  } catch (e) {
    coverMsg.value = errorMessage(e);
  } finally {
    coverBusy.value = false;
  }
}

async function load() {
  const [providerList, modelList] = await Promise.all([api.providers(), api.models()]);
  providers.value = providerList;
  models.value = modelList;
  if (!providers.value.some((p) => p.id === mForm.value.provider_id)) mForm.value.provider_id = null;
}

async function loadSettings() {
  try {
    const s = await api.getSettings();
    renderConcurrency.value = s.render_concurrency;
    ttsRate.value = s.tts_rate ?? 0;
  } catch (e) {
    error.value = errorMessage(e);
  }
}

async function saveSettings() {
  if (savingSettings.value) return;
  error.value = "";
  notice.value = "";
  savingSettings.value = true;
  try {
    const r = await api.updateSettings({
      render_concurrency: Number(renderConcurrency.value) || 1,
      tts_rate: Number(ttsRate.value) || 0,
    });
    renderConcurrency.value = r.render_concurrency;
    ttsRate.value = r.tts_rate ?? 0;
    const rate = r.tts_rate > 0 ? `+${r.tts_rate}%` : `${r.tts_rate}%`;
    notice.value = `渲染并发 ${r.render_concurrency}、默认语速 ${rate}（对后续任务生效）`;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    savingSettings.value = false;
  }
}

async function addProvider() {
  if (catalogBusy.value) return;
  error.value = "";
  if (!pForm.value.name.trim() || !pForm.value.base_url.trim()) {
    error.value = "请填写供应商名称和 Base URL";
    return;
  }
  catalogBusy.value = true;
  try {
    await api.createProvider({ ...pForm.value });
    pForm.value = { name: "", base_url: "", api_key: "", default_model_id: "" };
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

async function test(id: number) {
  if (catalogBusy.value) return;
  error.value = "";
  notice.value = "测试中…";
  catalogBusy.value = true;
  try {
    const r = await api.testProvider(id);
    notice.value = r.ok
      ? `连通正常（模型 ${r.model}，${r.latency_ms}ms）`
      : `失败：${r.error_type} · ${r.message}`;
  } catch (e) {
    notice.value = "";
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

async function removeProvider(p: AIProvider) {
  if (catalogBusy.value) return;
  if (!confirm(`删除供应商「${p.name}」及其下所有模型？`)) return;
  error.value = "";
  catalogBusy.value = true;
  try {
    await api.deleteProvider(p.id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

async function removeModel(m: AIModel) {
  if (catalogBusy.value) return;
  if (!confirm(`删除模型「${m.name}（${m.model_id}）」？`)) return;
  error.value = "";
  catalogBusy.value = true;
  try {
    await api.deleteModel(m.id);
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

async function addModel() {
  if (catalogBusy.value) return;
  error.value = "";
  if (!mForm.value.provider_id) {
    error.value = "请选择供应商";
    return;
  }
  if (!mForm.value.name.trim() || !mForm.value.model_id.trim()) {
    error.value = "请填写模型显示名称和 model_id";
    return;
  }
  catalogBusy.value = true;
  try {
    await api.createModel({ ...mForm.value, provider_id: mForm.value.provider_id });
    mForm.value = { provider_id: mForm.value.provider_id, name: "", model_id: "", capability: "text" };
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

async function changeCapability(m: AIModel, event: Event) {
  if (catalogBusy.value) return;
  const input = event.target as HTMLSelectElement;
  const capability = input.value;
  error.value = "";
  catalogBusy.value = true;
  try {
    await api.updateModel(m.id, { capability });
    await load();
  } catch (e) {
    input.value = m.capability;
    error.value = errorMessage(e);
  } finally {
    catalogBusy.value = false;
  }
}

onMounted(async () => {
  const results = await Promise.allSettled([load(), loadCover(), loadSettings()]);
  const failed = results.find((result) => result.status === "rejected");
  if (failed?.status === "rejected") error.value = errorMessage(failed.reason);
});
</script>

<template>
  <div class="stack" style="max-width: 920px">
    <h1>设置</h1>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="badge info">{{ notice }}</p>

    <div class="card stack">
      <h2>AI 供应商</h2>
      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>Base URL</th>
            <th>密钥</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in providers" :key="p.id">
            <td>{{ p.name }}</td>
            <td class="mono">{{ p.base_url }}</td>
            <td>
              <span class="badge" :class="p.has_api_key ? 'ok' : 'err'">
                {{ p.has_api_key ? "已配置" : "未配置" }}
              </span>
            </td>
            <td style="text-align: right; white-space: nowrap">
              <button :disabled="catalogBusy" class="btn sm" @click="test(p.id)"><PlugZap :size="13" /> 测试</button>
              <button :disabled="catalogBusy" class="btn sm danger" style="margin-left: 6px" @click="removeProvider(p)">
                <Trash2 :size="13" /> 删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>

      <div class="grid cols-3">
        <div class="field">
          <label>名称</label>
          <input v-model="pForm.name" class="input" placeholder="deepseek" />
        </div>
        <div class="field">
          <label>Base URL</label>
          <input v-model="pForm.base_url" class="input" placeholder="https://api.deepseek.com" />
        </div>
        <div class="field">
          <label>API Key</label>
          <input v-model="pForm.api_key" type="password" class="input" />
        </div>
        <div class="field">
          <label>默认模型 model_id（可选）</label>
          <input v-model="pForm.default_model_id" class="input" placeholder="deepseek-flash" />
        </div>
      </div>
      <div class="row">
        <button :disabled="catalogBusy" class="btn primary" @click="addProvider"><Plus :size="14" /> 添加供应商</button>
        <span class="muted">密钥以 Fernet 加密存储，接口不回显。填了「默认模型」会自动建一个文本模型。</span>
      </div>
    </div>

    <div class="card stack">
      <h2>模型</h2>
      <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>model_id</th>
            <th>能力</th>
            <th>供应商</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in models" :key="m.id">
            <td>{{ m.name }}</td>
            <td class="mono">{{ m.model_id }}</td>
            <td>
              <select
                :value="m.capability"
                class="input"
                style="min-width: 96px"
                :disabled="catalogBusy"
                @change="changeCapability(m, $event)"
              >
                <option v-for="c in modelCapabilities" :key="c" :value="c">{{ c }}</option>
                <option v-if="!modelCapabilities.includes(m.capability)" :value="m.capability">
                  {{ m.capability }}
                </option>
              </select>
            </td>
            <td class="muted">{{ providers.find((p) => p.id === m.provider_id)?.name || m.provider_id }}</td>
            <td style="text-align: right">
              <button :disabled="catalogBusy" class="btn sm danger" @click="removeModel(m)"><Trash2 :size="13" /> 删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <div class="grid cols-3">
        <div class="field">
          <label>供应商</label>
          <select v-model="mForm.provider_id" class="input">
            <option :value="null">选择供应商</option>
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="field">
          <label>显示名称</label>
          <input v-model="mForm.name" class="input" placeholder="DeepSeek v4 flash" />
        </div>
        <div class="field">
          <label>model_id</label>
          <input v-model="mForm.model_id" class="input" placeholder="deepseek-flash" />
        </div>
        <div class="field">
          <label>能力</label>
          <select v-model="mForm.capability" class="input">
            <option v-for="c in modelCapabilities" :key="c" :value="c">{{ c }}</option>
          </select>
          <small class="muted">支持图片输入的模型请登记为 vision，agent 才能读图自审。</small>
        </div>
      </div>
      <div class="row">
        <button :disabled="catalogBusy" class="btn primary" @click="addModel"><Plus :size="14" /> 添加模型</button>
      </div>
    </div>

    <div class="card stack">
      <h2>系统</h2>
      <div class="field" style="max-width: 320px">
        <label>渲染并发（Remotion 帧并发）</label>
        <input v-model.number="renderConcurrency" type="number" class="input" min="1" max="16" />
        <small class="muted">
          默认 1（4c8g 单机串行更稳）。内存充裕可调大以加速渲染；对后续渲染任务生效，持久保存。
        </small>
      </div>
      <div class="field" style="max-width: 420px">
        <label>默认语速（中文配音）</label>
        <div class="row" style="align-items: center; gap: 10px">
          <input v-model.number="ttsRate" type="range" min="-50" max="50" step="5" style="flex: 1" />
          <span class="mono" style="min-width: 52px; text-align: right">
            {{ ttsRate > 0 ? `+${ttsRate}%` : `${ttsRate}%` }}
          </span>
        </div>
        <small class="muted">
          新建项目的默认语速（负数更慢、正数更快）；单个项目可再单独覆盖。
        </small>
      </div>
      <div class="row">
        <button class="btn primary" :disabled="savingSettings" @click="saveSettings">
          {{ savingSettings ? "保存中…" : "保存" }}
        </button>
      </div>
    </div>

    <div class="card stack">
      <h2>AI 主题封面（独立配置）</h2>
      <p class="muted small">
        视频渲染成功后自动生成一张符合主题的炫酷封面。这里<strong>单独配置生图模型</strong>，与上面的「制作模型」互不影响；
        配好后无需在每个项目里再选择。
      </p>
      <div class="grid cols-3">
        <div class="field">
          <label>生图 Base URL</label>
          <input v-model="cover.base_url" class="input" placeholder="https://api.example.com" />
        </div>
        <div class="field">
          <label>模型名</label>
          <input v-model="cover.model" class="input" placeholder="如 flux-1 / dall-e-3 / wanx-v1" />
        </div>
        <div class="field">
          <label>尺寸（可选）</label>
          <input v-model="cover.size" class="input" placeholder="如 1792x1024；留空按画布比例" />
        </div>
        <div class="field">
          <label>API Key{{ cover.has_api_key ? "（已配置，留空保持不变）" : "" }}</label>
          <input v-model="coverApiKey" type="password" class="input" placeholder="sk-..." />
        </div>
      </div>
      <div class="row wrap">
        <button class="btn primary" :disabled="coverBusy" @click="saveCover">
          {{ coverBusy ? "处理中…" : "保存" }}
        </button>
        <button class="btn" :disabled="coverBusy" @click="testCover">测试生图</button>
        <span v-if="coverMsg" class="muted small">{{ coverMsg }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
table {
  margin-bottom: 8px;
}
.error {
  color: var(--err);
}
</style>
