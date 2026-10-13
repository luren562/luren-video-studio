import { defineStore } from "pinia";
import { api, TOKEN_KEY } from "../api";

const USER_KEY = "vf_user";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || "",
    username: localStorage.getItem(USER_KEY) || "",
  }),
  getters: {
    isAuthed: (state) => Boolean(state.token),
  },
  actions: {
    async login(username: string, password: string) {
      const token = await api.login(username, password);
      this.token = token.access_token;
      this.username = token.username;
      localStorage.setItem(TOKEN_KEY, token.access_token);
      localStorage.setItem(USER_KEY, token.username);
    },
    logout() {
      this.token = "";
      this.username = "";
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },
  },
});
