import { createRouter, createWebHistory } from "vue-router";
import { TOKEN_KEY } from "./api";

const routes = [
  { path: "/login", name: "login", component: () => import("./views/LoginView.vue") },
  {
    path: "/",
    component: () => import("./components/AppLayout.vue"),
    children: [
      { path: "", name: "dashboard", component: () => import("./views/DashboardView.vue") },
      { path: "projects", name: "projects", component: () => import("./views/ProjectsView.vue") },
      {
        path: "projects/new",
        name: "project-create",
        component: () => import("./views/ProjectCreateView.vue"),
      },
      {
        path: "projects/:id(\\d+)",
        name: "project-detail",
        component: () => import("./views/ProjectDetailView.vue"),
        props: true,
      },
      { path: "library", name: "library", component: () => import("./views/LibraryView.vue") },
      { path: "transcribe", name: "transcribe", component: () => import("./views/TranscribeView.vue") },
      { path: "styles", name: "styles", component: () => import("./views/StylesView.vue") },
      { path: "strategies", name: "strategies", component: () => import("./views/StrategiesView.vue") },
      { path: "tasks", name: "tasks", component: () => import("./views/TasksView.vue") },
      { path: "settings", name: "settings", component: () => import("./views/SettingsView.vue") },
    ],
  },
  { path: "/:pathMatch(.*)*", redirect: { name: "dashboard" } },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach((to) => {
  const authed = Boolean(localStorage.getItem(TOKEN_KEY));
  if (to.name !== "login" && !authed) {
    return { name: "login" };
  }
  if (to.name === "login" && authed) {
    return { name: "dashboard" };
  }
  return true;
});
