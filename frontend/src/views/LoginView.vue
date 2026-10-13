<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight, Eye, EyeOff, Film, Sparkles, Loader2 } from "lucide-vue-next";
import { errorMessage } from "../api";
import { useAuthStore } from "../stores/auth";
const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const username = ref("admin");
const password = ref("");
const visible = ref(false);
const error = ref("");
const loading = ref(false);
async function submit() {
  if (loading.value) return;
  error.value = "";
  if (!username.value.trim() || !password.value) { error.value = "请填写用户名和密码"; return; }
  loading.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    const redirect = route.query.redirect;
    await router.replace(typeof redirect === "string" && redirect.startsWith("/") && !redirect.startsWith("//") && !redirect.startsWith("/login") ? redirect : "/");
  } catch (e) { error.value = errorMessage(e); }
  finally { loading.value = false; }
}
</script>
<template>
  <div class="login-page">
    <section class="login-story">
      <a href="/" class="login-brand"><img src="/logo.png" width="48" height="48" alt="路仁" /><span>路仁<small>VIDEO STUDIO</small></span></a>
      <div class="story-content"><span class="story-kicker"><Sparkles :size="14" /> 为每一个创作的念头</span><h1>好故事，<br />值得被<span>看见。</span></h1><p>把灵感变成画面，把想法变成作品。<br />你的下一段故事，从这里开始。</p><div class="creative-window" aria-hidden="true"><div class="window-top"><i></i><i></i><i></i><span>CREATIVE SPACE</span></div><div class="window-scene"><div class="sun"></div><div class="hill"></div><div class="hill second"></div><Film :size="30" /></div><div class="window-bottom"><span>灵感 · 画面 · 表达</span><span>✦</span></div></div></div>
      <div class="story-footer">路仁视频工作室 <span>让创作，自然发生。</span></div>
    </section>
    <section class="login-form-area">
      <div class="login-form-wrap">
        <div class="mobile-brand"><img src="/logo.png" width="44" height="44" alt="路仁" /><span>路仁视频工作室</span></div>
        <span class="eyebrow">WELCOME BACK</span><h2>欢迎回到创作空间</h2><p class="intro">登录账号，继续你的灵感与创作。</p>
        <form class="login-form" @submit.prevent="submit">
          <div class="field"><label for="username">用户名</label><input id="username" v-model="username" name="username" class="input" autocomplete="username" required :disabled="loading" placeholder="输入用户名" /></div>
          <div class="field"><label for="password">密码</label><div class="password-field"><input id="password" v-model="password" name="password" :type="visible ? 'text' : 'password'" class="input" autocomplete="current-password" required :disabled="loading" placeholder="输入你的密码" /><button type="button" class="password-toggle" :aria-label="visible ? '隐藏密码' : '显示密码'" :aria-pressed="visible" @click="visible = !visible"><EyeOff v-if="visible" :size="17" /><Eye v-else :size="17" /></button></div></div>
          <p v-if="error" class="notice-error" role="alert">{{ error }}</p>
          <button class="btn primary login-submit" type="submit" :disabled="loading"><Loader2 v-if="loading" :size="17" class="spin" />{{ loading ? "正在进入工作室…" : "进入工作室" }}<ArrowRight v-if="!loading" :size="17" /></button>
        </form>
        <p class="login-note"><span></span> 专注创作，让每一帧都更有意义</p>
      </div>
      <p class="login-copyright">路仁 · AI 视频创作工作室</p>
    </section>
  </div>
</template>
<style scoped>
.login-page { min-height: 100vh; min-height: 100dvh; display: grid; grid-template-columns: 1fr 1fr; padding: 16px; background: #f7f8f3; }
.login-story { min-height: calc(100dvh - 32px); padding: 37px 44px 25px; background: #26372c; border-radius: 17px; color: #e7edde; display: flex; flex-direction: column; overflow: hidden; }
.login-brand { display: flex; align-items: center; gap: 13px; width: fit-content; }.login-brand img { border-radius: 10px; background: #000; }.login-brand > span { font-size: 22px; letter-spacing: 3px; line-height: 1.3; }.login-brand small { display: block; font-size: 8px; letter-spacing: 2.7px; margin-top: 5px; color: #a8b89f; }
.story-content { margin: auto; width: 100%; max-width: 365px; padding: 38px 0; }.story-kicker { font-size: 10px; letter-spacing: 1px; color: #afc19b; display: flex; gap: 8px; align-items: center; }.story-content h1 { font-size: 48px; font-weight: 400; line-height: 1.5; letter-spacing: 4px; margin: 18px 0; }.story-content h1 span { color: #cde0a8; }.story-content > p { color: #a9b89f; font-size: 12px; line-height: 2; }
.creative-window { width: 290px; background: #f7f8ed; border-radius: 10px; padding: 12px; margin: 35px 0 0 12px; transform: rotate(-6deg); box-shadow: 12px 16px 0 #a2bc8030; }.window-top { display: flex; align-items: center; gap: 4px; padding: 0 0 10px; }.window-top i { width: 4px; height: 4px; background: #b9c1ac; border-radius: 50%; }.window-top span { margin-left: auto; color: #8b9881; font-size: 7px; letter-spacing: 1.5px; }.window-scene { height: 120px; border-radius: 4px; background: #dce6c6; position: relative; overflow: hidden; display: grid; place-items: center; }.window-scene > svg { color: #ffffffb3; z-index: 2; }.sun { position: absolute; border-radius: 50%; width: 45px; height: 45px; right: 65px; top: 14px; background: #f8f7d5; }.hill { position: absolute; height: 130px; width: 350px; border-radius: 50%; background: #b7ca9d; top: 66px; left: -120px; transform: rotate(15deg); }.hill.second { left: 60px; top: 87px; background: #8fa474; transform: rotate(-15deg); }.window-bottom { display: flex; justify-content: space-between; padding-top: 9px; font-size: 8px; color: #7d8b6d; }.story-footer { display: flex; justify-content: space-between; gap: 12px; font-size: 9px; color: #8fa282; letter-spacing: .7px; }
.login-form-area { display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 50px 36px 22px; position: relative; }.login-form-wrap { width: 100%; max-width: 342px; margin: auto; }.eyebrow { font-size: 9px; letter-spacing: 2.4px; color: #909f83; }.login-form-wrap h2 { font-size: 26px; margin: 15px 0 11px; font-weight: 500; letter-spacing: .5px; }.intro { font-size: 12px; color: #8a9580; margin: 0 0 35px; }.login-form { display: flex; flex-direction: column; gap: 22px; }.login-form .input { background: #fff; padding: 13px 14px; }.password-field { position: relative; }.password-field .input { padding-right: 44px; }.password-toggle { position: absolute; right: 6px; top: 5px; bottom: 5px; border: 0; padding: 8px; display: flex; align-items: center; background: transparent; color: #8a977e; cursor: pointer; border-radius: 6px; }.login-submit { margin-top: 5px; width: 100%; min-height: 46px; }.login-submit > svg:last-child { margin-left: auto; }.login-note { margin: 26px 0 0; color: #9ba58e; font-size: 10px; text-align: center; }.login-note span { display: inline-block; width: 4px; height: 4px; background: #98ad7e; border-radius: 50%; vertical-align: middle; margin-right: 6px; }.login-copyright { font-size: 9px; color: #9ca68f; letter-spacing: 1px; margin: 48px 0 0; }.mobile-brand { display: none; }.notice-error { margin: 0; }.spin { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 950px) { .login-story { padding-inline: 30px; }.story-content h1 { font-size: 39px; }.creative-window { width: 240px; }.story-footer span { display: none; }.login-form-area { padding-inline: 30px; } }
@media (max-width: 700px) { .login-page { grid-template-columns: 1fr; padding: 0; }.login-story { display: none; }.login-form-area { min-height: 100dvh; padding: 45px 28px 24px; }.mobile-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 55px; font-size: 13px; color: #64705b; }.mobile-brand img { border-radius: 10px; background: black; }.login-form-wrap h2 { font-size: 25px; }.login-form .input { font-size: 16px; } }
</style>
