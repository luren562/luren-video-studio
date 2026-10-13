<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { LayoutDashboard, FolderKanban, Library, FileText, Palette, Sparkles, ListChecks, Settings, Plus, LogOut, Loader2, Menu, X, ChevronRight, ArrowUpRight } from "lucide-vue-next";
import { api } from "../api";
import { useAuthStore } from "../stores/auth";
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const running = ref(0);
const queued = ref(0);
const connected = ref<boolean | null>(null);
const mobileOpen = ref(false);
const menuButton = ref<HTMLButtonElement | null>(null);
const sidebar = ref<HTMLElement | null>(null);
const content = ref<HTMLElement | null>(null);
let timer: number | undefined;
let disposed = false;
const groups = [
  { label: "工作空间", items: [
    { name: "dashboard", label: "创作概览", icon: LayoutDashboard },
    { name: "projects", label: "需求工作台", icon: FolderKanban },
    { name: "library", label: "成片库", icon: Library },
  ] },
  { label: "创作工具", items: [
    { name: "transcribe", label: "视频转文稿", icon: FileText },
    { name: "styles", label: "风格档", icon: Palette },
    { name: "strategies", label: "创作策略", icon: Sparkles },
  ] },
  { label: "管理", items: [
    { name: "tasks", label: "任务中心", icon: ListChecks },
    { name: "settings", label: "设置", icon: Settings },
  ] },
];
const isActive = (name: string) => name === "projects"
  ? ["projects", "project-detail", "project-create"].includes(String(route.name))
  : route.name === name;
const pageTitle = computed(() => route.name === "project-create" ? "新建需求"
  : route.name === "project-detail" ? "项目详情"
  : groups.flatMap((g) => g.items).find((item) => item.name === route.name)?.label || "工作空间");
const queueText = computed(() => connected.value === null ? "连接中"
  : !connected.value ? "连接暂不可用"
  : running.value || queued.value ? "执行 " + running.value + " · 排队 " + queued.value : "就绪，开始创作");
async function refreshQueue() {
  try {
    const stats = await api.stats();
    if (disposed) return;
    running.value = stats.tasks_running;
    queued.value = stats.tasks_queued;
    connected.value = true;
  } catch { if (!disposed) connected.value = false; }
  finally { if (!disposed) timer = window.setTimeout(refreshQueue, 10000); }
}
async function toggleMenu() {
  mobileOpen.value = !mobileOpen.value;
  if (mobileOpen.value) {
    await nextTick();
    sidebar.value?.querySelector<HTMLButtonElement>("button")?.focus();
  }
}
function closeMenu(returnFocus = false) {
  mobileOpen.value = false;
  if (returnFocus) menuButton.value?.focus();
}
function menuKeys(event: KeyboardEvent) {
  if (!mobileOpen.value) return;
  if (event.key === "Escape") { event.preventDefault(); closeMenu(true); }
  if (event.key !== "Tab") return;
  const elements = sidebar.value?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
  if (!elements?.length) return;
  const first = elements[0]!;
  const last = elements[elements.length - 1]!;
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
watch(() => route.fullPath, async () => {
  const wasOpen = mobileOpen.value;
  closeMenu();
  await nextTick();
  content.value?.scrollTo({ top: 0 });
  if (wasOpen) content.value?.focus();
});
onMounted(() => { refreshQueue(); document.addEventListener("keydown", menuKeys); });
onUnmounted(() => { disposed = true; window.clearTimeout(timer); document.removeEventListener("keydown", menuKeys); });
function logout() { auth.logout(); router.push({ name: "login" }); }
</script>
<template>
  <div class="layout">
    <a class="skip-link" href="#workspace-content">跳转到主要内容</a>
    <div v-if="mobileOpen" class="sidebar-backdrop" @click="closeMenu(true)"></div>
    <aside id="workspace-sidebar" ref="sidebar" class="sidebar" :class="{ 'is-open': mobileOpen }" aria-label="主导航">
      <div class="brand-row">
        <router-link to="/" class="brand" aria-label="路仁视频工作室首页">
          <img src="/logo.png" alt="路仁" width="46" height="46" />
          <span><strong>路仁<span class="brand-dot">.</span></strong><small>VIDEO STUDIO</small></span>
        </router-link>
        <button class="sidebar-close icon-button" aria-label="关闭导航" @click="closeMenu(true)"><X :size="20" /></button>
      </div>
      <router-link :to="{ name: 'project-create' }" class="sidebar-create"><Plus :size="17" /> 开始新的创作 <span>+</span></router-link>
      <nav class="sidebar-nav">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <p class="nav-label">{{ group.label }}</p>
          <router-link v-for="item in group.items" :key="item.name" :to="{ name: item.name }" class="nav-item" :class="{ active: isActive(item.name) }" :aria-current="isActive(item.name) ? 'page' : undefined">
            <component :is="item.icon" :size="18" /><span>{{ item.label }}</span>
            <span v-if="item.name === 'tasks' && connected && running + queued" class="nav-count">{{ running + queued }}</span>
          </router-link>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="studio-note"><Sparkles :size="17" /><p>灵感在此，作品由你。<small>从一个想法，到下一部作品</small></p></div>
        <div class="account"><div class="avatar">{{ (auth.username || 'A').slice(0, 1).toUpperCase() }}</div><div class="account-name"><strong>{{ auth.username || "创作者" }}</strong><small>创作工作空间</small></div><button class="icon-button" title="退出登录" aria-label="退出登录" @click="logout"><LogOut :size="17" /></button></div>
      </div>
    </aside>
    <div class="main" :inert="mobileOpen || undefined">
      <header class="topbar">
        <button ref="menuButton" class="mobile-menu btn ghost icon-button" aria-label="打开导航" aria-controls="workspace-sidebar" :aria-expanded="mobileOpen" @click="toggleMenu"><Menu :size="21" /></button>
        <div class="breadcrumb"><span>工作空间</span><ChevronRight :size="14" /><strong>{{ pageTitle }}</strong></div>
        <div class="topbar-actions"><span class="queue-status" :class="{ offline: connected === false }" role="status"><Loader2 v-if="running > 0 && connected" :size="13" class="spin" /><i v-else></i>{{ queueText }}</span><router-link :to="{ name: 'project-create' }" class="btn primary sm"><Plus :size="15" /><span>新建需求</span><ArrowUpRight :size="13" /></router-link></div>
      </header>
      <main id="workspace-content" ref="content" class="content" tabindex="-1"><div class="content-inner"><router-view /></div><footer class="workspace-footer"><span>路仁视频工作室</span><span>让创作，自然发生。</span></footer></main>
    </div>
  </div>
</template>
<style scoped>
.layout { display: flex; height: 100vh; height: 100dvh; overflow: hidden; }
.sidebar { width: 232px; flex-shrink: 0; background: #202923; color: #e5eae5; padding: 28px 17px 0; display: flex; flex-direction: column; overflow-y: auto; }
.brand-row { display: flex; align-items: center; justify-content: space-between; margin: 0 10px 28px; }
.brand { display: flex; align-items: center; gap: 12px; }
.brand img { border-radius: 11px; object-fit: contain; background: #000; }
.brand strong { display: block; font-size: 22px; letter-spacing: 2px; line-height: 1.2; color: #fff; }
.brand-dot { color: #d2e5a0; }
.brand small { display: block; margin-top: 6px; color: #a8b5ac; font-size: 9px; letter-spacing: 2.3px; }
.sidebar-create { display: flex; align-items: center; gap: 8px; padding: 12px 13px; background: #d7e9ae; color: #273923; border-radius: 9px; font-weight: 600; font-size: 13px; transition: background .2s; }
.sidebar-create:hover { background: #e3f2c2; }.sidebar-create span { margin-left: auto; opacity: .45; }
.sidebar-nav { padding-top: 24px; }.nav-group + .nav-group { margin-top: 22px; }
.nav-label { margin: 0 12px 8px; font-size: 10px; letter-spacing: 1.6px; color: #95a69b; }
.nav-item { display: flex; align-items: center; gap: 11px; padding: 11px 13px; margin: 3px 0; border-radius: 8px; color: #bcc8bf; font-size: 13px; transition: background .2s, color .2s; }
.nav-item:hover { background: #2d3830; color: #fff; }.nav-item.active { background: #354337; color: #e2f0bc; box-shadow: inset 2px 0 0 #c5df8e; }
.nav-count { margin-left: auto; border-radius: 5px; background: #4b5c43; padding: 0 6px; font-size: 11px; }
.sidebar-bottom { margin-top: auto; padding-top: 26px; }.studio-note { display: flex; gap: 10px; align-items: center; padding: 14px 10px 22px; color: #c0d0ae; }.studio-note p { margin: 0; font-size: 11px; }.studio-note small { display: block; font-size: 10px; color: #92a497; margin-top: 5px; }
.account { display: flex; align-items: center; gap: 10px; padding: 20px 3px; border-top: 1px solid #3a453d; }.avatar { width: 32px; height: 32px; display: grid; place-items: center; background: #435045; color: #e1eacb; border-radius: 50%; font-size: 12px; }
.account-name { flex: 1; min-width: 0; }.account-name strong { display: block; font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; }.account-name small { display: block; font-size: 10px; color: #9fac9f; margin-top: 2px; }
.icon-button { display: inline-flex; align-items: center; justify-content: center; border: 0; background: transparent; color: inherit; padding: 8px; border-radius: 7px; cursor: pointer; }.icon-button:hover { background: #ffffff12; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }.topbar { min-height: 74px; flex-shrink: 0; display: flex; align-items: center; gap: 12px; padding: 0 38px; background: #fcfcf9; border-bottom: 1px solid var(--border); }
.breadcrumb { display: flex; gap: 12px; align-items: center; color: #8b9189; font-size: 12px; }.breadcrumb strong { color: #495247; font-weight: 500; }
.topbar-actions { margin-left: auto; display: flex; align-items: center; gap: 24px; }.topbar-actions .btn { gap: 7px; }
.queue-status { display: flex; align-items: center; gap: 7px; color: #6a7569; font-size: 11px; }.queue-status i { width: 6px; height: 6px; background: #84a36e; border-radius: 50%; box-shadow: 0 0 0 3px #eef3e8; }.queue-status.offline i { background: #bd8b4a; box-shadow: 0 0 0 3px #fbf0de; }
.content { flex: 1; overflow: auto; padding: 34px 38px 0; outline: none; scrollbar-gutter: stable; }.content-inner { width: 100%; max-width: 1440px; margin: 0 auto; min-height: calc(100% - 65px); }
.workspace-footer { max-width: 1440px; margin: 26px auto 0; border-top: 1px solid var(--border); min-height: 46px; display: flex; align-items: center; justify-content: space-between; font-size: 10px; letter-spacing: .6px; color: #8b9389; }
.mobile-menu, .sidebar-close, .sidebar-backdrop { display: none; }.spin { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1200px) { .sidebar { width: 212px; padding-inline: 13px; }.topbar { padding-inline: 26px; }.content { padding: 26px 24px 0; } }
@media (max-width: 760px) { .sidebar { position: fixed; inset: 0 auto 0 0; width: 254px; z-index: 100; transform: translateX(-100%); visibility: hidden; transition: transform .2s, visibility .2s; }.sidebar.is-open { visibility: visible; transform: translateX(0); }.sidebar-close, .mobile-menu { display: inline-flex; }.sidebar-backdrop { display: block; position: fixed; inset: 0; z-index: 90; background: #15251b80; backdrop-filter: blur(3px); }.brand-row { margin-inline: 6px; }.topbar { min-height: 65px; padding-inline: 14px; gap: 8px; }.topbar-actions { gap: 10px; }.breadcrumb { gap: 6px; }.breadcrumb > span, .breadcrumb > svg { display: none; }.queue-status { display: none; }.content { padding: 24px 18px 0; scrollbar-gutter: auto; }.topbar-actions .btn > svg:last-child { display: none; } }
</style>
