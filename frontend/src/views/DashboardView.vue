<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Film, FolderKanban, CheckCircle2, Clock3, ArrowUpRight, ArrowRight, Plus, FileText, Palette, Sparkles, Play, RefreshCw, ListVideo, Check, AlertCircle } from "lucide-vue-next";
import { api, errorMessage, outputPosterUrl, outputCoverUrl } from "../api";
import type { PipelineTask, RenderOutput, Stats } from "../types";
import { engineLabel, framesToDuration, outputStatus, formatDateTime } from "../utils";
const stats = ref<Stats | null>(null);
const recentOutputs = ref<RenderOutput[]>([]);
const activeTasks = ref<PipelineTask[]>([]);
const loading = ref(true);
const error = ref("");
const failedImages = ref(new Set<number>());
let timer: number | undefined;
let disposed = false;
let inFlight = false;
const statCards = computed(() => [
  { label: "创作项目", value: stats.value?.projects_total, note: stats.value ? stats.value.projects_in_progress + " 个项目进行中" : "正在获取项目数据", icon: FolderKanban, tone: "green" },
  { label: "产出成片", value: stats.value?.outputs_total, note: "每个想法，都有回响", icon: Film, tone: "blue" },
  { label: "已入库作品", value: stats.value?.outputs_completed, note: "通过质量检查的成片", icon: CheckCircle2, tone: "olive" },
  { label: "制作队列", value: stats.value ? stats.value.tasks_running + stats.value.tasks_queued : undefined, note: stats.value ? stats.value.tasks_failed + " 个任务需要关注" : "正在获取任务状态", icon: Clock3, tone: "sand" },
]);
async function load() {
  if (inFlight || disposed) return;
  window.clearTimeout(timer);
  inFlight = true;
  const results = await Promise.allSettled([
    api.stats(), api.outputs({}),
    api.tasks({ status: "running", limit: 6 }),
    api.tasks({ status: "queued", limit: 6 }),
  ]);
  if (disposed) return;
  const [statsResult, outputResult, runningResult, queuedResult] = results;
  if (statsResult.status === "fulfilled") stats.value = statsResult.value;
  if (outputResult.status === "fulfilled") recentOutputs.value = outputResult.value.slice(0, 3);
  if (runningResult.status === "fulfilled" && queuedResult.status === "fulfilled") {
    activeTasks.value = [...runningResult.value, ...queuedResult.value].slice(0, 5);
  }
  const failure = results.find((r) => r.status === "rejected");
  error.value = failure?.status === "rejected" ? "部分数据加载失败：" + errorMessage(failure.reason) : "";
  loading.value = false;
  inFlight = false;
  timer = window.setTimeout(load, 15000);
}
const kindLabel = (kind: string) => ({ agent: "视频创作", render: "视频渲染", cover: "封面制作", transcribe: "视频转文稿", transcription: "视频转文稿", generate: "内容生成" }[kind] || kind);
const progress = (task: PipelineTask) => Math.min(100, Math.max(0, task.progress_total > 0 ? Math.round(task.progress_current / task.progress_total * 100) : 0));
onMounted(load);
onUnmounted(() => { disposed = true; window.clearTimeout(timer); });
</script>
<template>
  <div class="dashboard stack">
    <div class="page-heading row between">
      <div><div class="eyebrow">YOUR CREATIVE SPACE</div><h1>创作，从一个好想法开始<span>。</span></h1><p>把灵感交给创作，让每一帧都有表达。</p></div>
      <router-link :to="{ name: 'projects' }" class="text-link">查看我的项目 <ArrowUpRight :size="15" /></router-link>
    </div>
    <div v-if="error" class="notice-error" role="alert"><span><AlertCircle :size="14" /> {{ error }}</span><button class="btn sm" @click="load"><RefreshCw :size="13" />重新加载</button></div>
    <section class="hero" aria-label="开始视频创作">
      <div class="hero-copy">
        <span class="hero-kicker"><Sparkles :size="13" /> AI 视频创作工作室</span>
        <h2>让灵感成形，<br />让故事被看见。</h2>
        <p>从一句需求，到一部完整作品。<br class="mobile-break" />分镜、配音与画面，在这里自然衔接。</p>
        <router-link :to="{ name: 'project-create' }" class="btn hero-cta"><Plus :size="16" /> 开始创作 <ArrowUpRight :size="15" /></router-link>
      </div>
      <div class="hero-art" aria-hidden="true">
        <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
        <div class="story-card story-back"><span>01 / THE IDEA</span><div class="story-lines"><i></i><i></i><i></i></div><div class="story-caption">一个想法，无限可能</div></div>
        <div class="story-card story-front"><div class="story-top"><span>YOUR NEXT STORY</span><span>16:9</span></div><div class="story-scene"><div class="scene-sun"></div><div class="scene-hill hill-back"></div><div class="scene-hill hill-front"></div><div class="play-circle"><Play :size="18" fill="currentColor" /></div></div><div class="story-bottom"><span>把想象，变成画面</span><span>✦</span></div></div>
        <div class="art-tag"><span><Check :size="11" /></span> 让创作，自然发生</div>
      </div>
    </section>
    <section class="grid cols-4 stat-grid" aria-label="创作数据" :aria-busy="loading">
      <div v-for="stat in statCards" :key="stat.label" class="card stat">
        <div class="row between"><span class="stat-label">{{ stat.label }}</span><span class="stat-icon" :class="stat.tone"><component :is="stat.icon" :size="17" /></span></div>
        <div class="stat-number">{{ stat.value ?? "—" }}<span v-if="stat.value !== undefined">个</span></div><p>{{ stat.note }}</p>
      </div>
    </section>
    <section class="quick-actions" aria-label="创作快捷入口">
      <router-link :to="{ name: 'project-create' }"><span class="quick-icon"><ListVideo :size="20" /></span><div><strong>新建视频需求</strong><small>写下想法，开启下一部作品</small></div><ArrowUpRight :size="17" /></router-link>
      <router-link :to="{ name: 'transcribe' }"><span class="quick-icon"><FileText :size="20" /></span><div><strong>视频转文稿</strong><small>从视频中提取文字与灵感</small></div><ArrowUpRight :size="17" /></router-link>
      <router-link :to="{ name: 'styles' }"><span class="quick-icon"><Palette :size="20" /></span><div><strong>探索创作风格</strong><small>找到属于你的画面表达</small></div><ArrowUpRight :size="17" /></router-link>
    </section>
    <div class="dashboard-bottom">
      <section class="card recent-section">
        <div class="section-heading row between"><div><h2>最近作品<span class="section-en">RECENT WORK</span></h2><p>每一次创作，都值得被珍藏。</p></div><router-link :to="{ name: 'library' }" class="text-link">全部作品 <ArrowRight :size="14" /></router-link></div>
        <div v-if="loading" class="empty-state" role="status"><RefreshCw :size="24" /><p>正在整理你的作品…</p></div>
        <div v-else-if="recentOutputs.length" class="recent-grid">
          <router-link v-for="o in recentOutputs" :key="o.id" :to="{ name: 'library', query: { output: o.id } }" class="output-card">
            <div class="thumb"><img v-if="!failedImages.has(o.id) && (o.poster_path || o.cover_status === 'ready')" :src="o.cover_status === 'ready' ? outputCoverUrl(o.id) : outputPosterUrl(o.id)" :alt="engineLabel(o.engine) + '作品封面'" @error="failedImages.add(o.id)" /><Film v-else :size="25" /><span class="thumb-duration">{{ framesToDuration(o.duration_frames, o.fps) }}</span><span class="thumb-play"><Play :size="13" fill="currentColor" /></span></div>
            <div class="output-meta"><strong>{{ engineLabel(o.engine) }} <span>#{{ o.id }}</span></strong><span class="badge" :class="outputStatus(o.status).cls">{{ outputStatus(o.status).label }}</span></div><p class="output-date">{{ formatDateTime(o.created_at) }}</p>
          </router-link>
        </div>
        <div v-else class="empty-state"><div class="empty-icon"><Film :size="25" /></div><h3>{{ error ? "作品暂时无法显示" : "你的第一部作品，从这里开始" }}</h3><p>{{ error ? "请稍后重试，已保存的作品不会受影响。" : "把一个好想法，变成值得分享的画面。" }}</p><router-link v-if="!error" :to="{ name: 'project-create' }" class="text-link">创建第一部作品 <ArrowUpRight :size="14" /></router-link></div>
      </section>
      <section class="card task-section">
        <div class="section-heading row between"><div><h2>制作动态 <span class="activity-dot"></span></h2><p>关注作品的每一步进展。</p></div><router-link :to="{ name: 'tasks' }" class="text-link" aria-label="查看全部任务"><ArrowUpRight :size="17" /></router-link></div>
        <div v-if="activeTasks.length" class="task-list">
          <router-link v-for="t in activeTasks" :key="t.id" :to="{ name: 'tasks' }" class="task-item">
            <div class="row between"><strong>{{ kindLabel(t.kind) }} <span>#{{ t.id }}</span></strong><span class="badge" :class="t.status === 'running' ? 'run' : ''">{{ t.status === "running" ? "制作中" : "排队中" }}</span></div>
            <div class="progress" v-if="t.status === 'running'"><span :style="{ width: progress(t) + '%' }"></span></div>
            <div class="task-note"><span>{{ t.status === "running" ? "正在把想法变成作品" : "已准备好，等待开始" }}</span><span v-if="t.status === 'running'">{{ progress(t) }}%</span></div>
          </router-link>
        </div>
        <div v-else class="empty-state task-empty"><div class="empty-icon"><CheckCircle2 :size="25" /></div><h3>{{ loading ? "正在获取动态…" : error ? "动态暂时无法显示" : "一切就绪，等你的新灵感" }}</h3><p>{{ loading || error ? "任务状态会在连接恢复后更新。" : "当前没有排队或制作中的任务" }}</p></div>
        <router-link :to="{ name: 'tasks' }" class="task-footer">前往任务中心 <ArrowRight :size="14" /></router-link>
      </section>
    </div>
  </div>
</template>
<style scoped>
.dashboard { gap: 24px; }.eyebrow { font-size: 9px; letter-spacing: 2.2px; color: #88917f; margin-bottom: 10px; }.page-heading h1 { font-size: 25px; font-weight: 600; letter-spacing: -.8px; }.page-heading h1 > span { color: #759155; }.page-heading p { margin: 9px 0 0; color: var(--text-muted); font-size: 12px; }
.text-link { display: inline-flex; align-items: center; gap: 7px; font-size: 11px; color: #64715c; white-space: nowrap; }.text-link:hover { color: var(--accent); }
.hero { position: relative; display: flex; align-items: center; min-height: 267px; border-radius: 16px; background: #e8eddc; overflow: hidden; padding: 31px 38px; border: 1px solid #dfe6d2; }
.hero-copy { z-index: 1; width: 59%; }.hero-kicker { font-size: 10px; letter-spacing: 1px; color: #677a54; display: flex; align-items: center; gap: 7px; }.hero h2 { font-size: 31px; line-height: 1.5; font-weight: 500; letter-spacing: 1.4px; margin: 12px 0 11px; color: #30442e; }.hero p { font-size: 11px; color: #7a856c; margin: 0 0 21px; }.hero-cta { color: #f4f7ed; background: #344f36; border: 0; font-size: 12px; gap: 10px; }.hero-cta:hover:not(:disabled) { background: #263d28; color: white; }.mobile-break { display: none; }
.hero-art { position: absolute; inset: 0 0 0 55%; }.orbit { position: absolute; border: 1px solid #ccd6bc; border-radius: 50%; width: 350px; height: 350px; right: -8px; top: -50px; }.orbit-two { width: 470px; height: 470px; top: -109px; right: -69px; }.story-card { position: absolute; border: 1px solid #eff1e8; border-radius: 11px; box-shadow: 0 15px 25px #52653e14; }.story-back { width: 204px; height: 148px; top: 40px; right: 124px; transform: rotate(-13deg); padding: 16px; background: #f7f8f1; }.story-back > span { font-size: 7px; letter-spacing: 1.4px; color: #8b987e; }.story-lines { display: grid; gap: 7px; margin: 19px 0; }.story-lines i { width: 75%; height: 5px; background: #dce3cf; border-radius: 3px; }.story-lines i:nth-child(2) { width: 90%; }.story-lines i:nth-child(3) { width: 54%; }.story-caption { font-size: 9px; color: #7b896e; }
.story-front { width: 227px; right: 42px; top: 65px; transform: rotate(8deg); padding: 10px; background: #fffef8; }.story-top, .story-bottom { display: flex; align-items: center; justify-content: space-between; font-size: 7px; color: #768064; letter-spacing: .8px; padding: 2px 2px 9px; }.story-bottom { padding: 9px 2px 0; font-size: 9px; }.story-scene { height: 124px; border-radius: 5px; background: #dbe4c7; overflow: hidden; position: relative; }.scene-sun { width: 41px; height: 41px; background: #f6f5d5; position: absolute; border-radius: 50%; right: 37px; top: 16px; }.scene-hill { position: absolute; width: 245px; height: 95px; border-radius: 50%; bottom: -48px; background: #8fa473; transform: rotate(-17deg); right: -19px; }.hill-back { bottom: -28px; right: 78px; background: #bacba0; transform: rotate(17deg); }.play-circle { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #ffffffb3; color: #647d4c; border: 1px solid white; width: 37px; height: 37px; border-radius: 50%; display: grid; place-items: center; padding-left: 2px; }.art-tag { position: absolute; right: 116px; top: 232px; display: flex; align-items: center; gap: 7px; padding: 7px 12px; font-size: 8px; color: #6d7d57; border-radius: 20px; background: #ffffffdf; border: 1px solid #e6ebdb; transform: rotate(-4deg); }.art-tag > span { display: grid; place-items: center; background: #d4e4b9; width: 16px; height: 16px; border-radius: 50%; }
.stat-grid { gap: 16px; }.stat { padding: 17px 21px; }.stat-label { color: #7e8776; font-size: 11px; }.stat-icon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; }.green { background: #f0f5e9; color: #6c8b53; }.blue { background: #edf2f5; color: #7693a4; }.olive { background: #f5f3e7; color: #999053; }.sand { background: #f7efe9; color: #b48b67; }.stat-number { font-size: 31px; font-weight: 500; font-variant-numeric: tabular-nums; letter-spacing: -1px; margin: 1px 0 2px; }.stat-number > span { font-size: 10px; color: #92998b; margin-left: 9px; }.stat p { font-size: 10px; color: #89917f; margin: 0; }
.quick-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--border); border-radius: 12px; background: #fafbf7; padding: 17px 4px; }.quick-actions > a { min-width: 0; display: flex; align-items: center; gap: 13px; padding: 2px 22px; }.quick-actions > a + a { border-left: 1px solid var(--border); }.quick-icon { color: #879775; }.quick-actions strong { font-size: 12px; font-weight: 500; }.quick-actions small { display: block; font-size: 10px; color: #8c9484; margin-top: 5px; }.quick-actions > a > svg { margin-left: auto; color: #8e9981; }.quick-actions > a:hover strong { color: var(--accent); }
.dashboard-bottom { display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(0, 1fr); gap: 22px; }.section-heading h2 { font-size: 14px; }.section-en { font-size: 8px; letter-spacing: 1.5px; color: #9ca48f; margin-left: 12px; font-weight: 400; }.section-heading p { font-size: 10px; color: #969d8e; margin: 6px 0 0; }.empty-state { display: flex; align-items: center; flex-direction: column; justify-content: center; min-height: 214px; text-align: center; padding: 25px 8px; color: #94a186; }.empty-icon { width: 50px; height: 50px; border-radius: 16px; display: grid; place-items: center; border: 1px solid #e8eddf; background: #f7f9f1; margin-bottom: 15px; }.empty-state h3 { font-size: 12px; font-weight: 500; color: #68775c; }.empty-state p { margin: 8px 0 14px; font-size: 10px; color: #8f9a83; }
.recent-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; margin-top: 23px; }.output-card { min-width: 0; }.thumb { position: relative; aspect-ratio: 16/10; background: #e7ecdf; display: grid; place-items: center; border-radius: 8px; overflow: hidden; color: #a2b18d; }.thumb img { width: 100%; height: 100%; object-fit: cover; }.thumb-duration { position: absolute; bottom: 7px; right: 7px; color: #fff; font-size: 9px; border-radius: 4px; background: #1c2e24ad; padding: 1px 5px; }.thumb-play { position: absolute; top: 9px; left: 9px; width: 23px; height: 23px; border-radius: 50%; background: #ffffffb3; color: #627951; display: grid; place-items: center; }.output-meta { display: flex; align-items: flex-start; flex-direction: column; gap: 6px; margin-top: 11px; }.output-meta strong { font-size: 11px; font-weight: 500; }.output-meta strong > span { color: #8b947f; font-size: 9px; margin-left: 3px; }.output-date { font-size: 9px; color: #939b87; margin: 7px 0 0; }
.task-section { display: flex; flex-direction: column; }.activity-dot { display: inline-block; width: 5px; height: 5px; background: #89a56a; border-radius: 50%; vertical-align: middle; margin-left: 5px; }.task-list { margin-top: 12px; flex: 1; }.task-item { display: block; padding: 13px 0; border-bottom: 1px solid #eef0e9; }.task-item:last-child { border-bottom: 0; }.task-item strong { font-size: 11px; font-weight: 500; }.task-item strong > span { font-size: 9px; color: #9ca58e; margin-left: 5px; }.task-item .progress { margin-top: 12px; height: 4px; }.task-note { display: flex; justify-content: space-between; font-size: 9px; color: #929d83; margin-top: 7px; }.task-empty { min-height: 180px; flex: 1; }.task-footer { border-top: 1px solid #edf0e7; padding-top: 13px; margin-top: 8px; color: #839274; display: flex; justify-content: space-between; align-items: center; font-size: 10px; }.notice-error > span { display: flex; gap: 8px; align-items: center; }
@media (min-width: 1600px) { .hero-art { right: 6%; } }
@media (max-width: 1200px) { .hero { padding-inline: 28px; }.story-front { right: 21px; width: 200px; }.story-back { right: 100px; width: 175px; }.art-tag { right: 57px; top: 226px; }.hero h2 { font-size: 28px; }.quick-actions > a { padding-inline: 15px; gap: 9px; }.quick-actions small { font-size: 9px; }.dashboard-bottom { grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); }.section-en { display: none; } }
@media (min-width: 900px) { .stat-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 950px) { .hero-art { opacity: .7; right: -20px; }.hero-copy { width: 65%; }.hero p { max-width: 250px; }.hero h2 { font-size: 25px; }.dashboard-bottom { grid-template-columns: minmax(0, 1fr); }.quick-actions > a > svg { display: none; }.quick-actions > a { align-items: flex-start; }.quick-actions small { line-height: 1.6; }.page-heading > .text-link { display: none; } }
@media (max-width: 600px) { .dashboard { gap: 18px; }.page-heading h1 { font-size: 21px; }.eyebrow { font-size: 8px; }.hero { min-height: 248px; padding: 24px; }.hero-copy { width: 100%; }.hero h2 { font-size: 27px; }.hero p { max-width: 240px; position: relative; z-index: 1; }.hero-art { opacity: .25; inset: 0 -135px 0 45%; pointer-events: none; }.hero-kicker { font-size: 9px; }.hero-cta { position: relative; }.quick-actions { grid-template-columns: 1fr; padding: 0 18px; }.quick-actions > a { padding: 15px 0; align-items: center; }.quick-actions > a + a { border-left: 0; border-top: 1px solid var(--border); }.quick-actions small { font-size: 10px; margin-top: 3px; }.quick-actions > a > svg { display: block; }.quick-icon { width: 30px; }.stat { padding: 14px; }.stat-number { font-size: 27px; }.stat p { font-size: 9px; }.recent-grid { grid-template-columns: minmax(0, 1fr); gap: 21px; }.output-meta { flex-direction: row; justify-content: space-between; }.thumb { aspect-ratio: 16/9; }.section-heading p { font-size: 10px; } }
</style>
