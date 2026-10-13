import axios from "axios";
import type {
  AIModel,
  AIProvider,
  ContentStrategy,
  CoverConfig,
  Engine,
  PipelineEvent,
  PipelineTask,
  ProviderTestResult,
  RenderOutput,
  Stats,
  StrategyPayload,
  Token,
  VideoProject,
  VideoProjectDetail,
  VideoStyle,
  TtsVoice,
  TranscriptionJob,
  TranscriptionSummary,
} from "./types";

export const TOKEN_KEY = "vf_token";

const http = axios.create({ baseURL: "/" });

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && location.pathname !== "/login") {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem("vf_user");
      location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export function errorMessage(error: unknown): string {
  const axiosErr = error as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = axiosErr?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((d) => d && typeof d === "object" && "msg" in d ? String(d.msg) : "").filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return axiosErr?.message ?? "请求失败";
}

export const api = {
  async ttsVoices(): Promise<TtsVoice[]> {
    return (await http.get<TtsVoice[]>("/api/tts/voices")).data;
  },
  async previewVoice(voice: string, rate?: number | null): Promise<Blob> {
    try {
      return (await http.post("/api/tts/preview", { voice, rate }, { responseType: "blob" })).data;
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.data instanceof Blob) {
        try {
          const detail = JSON.parse(await e.response.data.text()).detail;
          if (typeof detail === "string") throw new Error(detail);
        } catch (parsed) {
          if (parsed instanceof Error && !(parsed instanceof SyntaxError)) throw parsed;
        }
      }
      throw e;
    }
  },
  async uploadNarration(file: File): Promise<{ id: number; filename: string }> {
    const form = new FormData();
    form.append("file", file);
    return (await http.post("/api/media-assets", form)).data;
  },
  async login(username: string, password: string): Promise<Token> {
    const { data } = await http.post<Token>("/api/auth/login", { username, password });
    return data;
  },

  async stats(): Promise<Stats> {
    const { data } = await http.get<Stats>("/api/stats");
    return data;
  },

  // --- AI ---
  async providers(): Promise<AIProvider[]> {
    return (await http.get<AIProvider[]>("/api/ai/providers")).data;
  },
  async createProvider(payload: {
    name: string;
    base_url: string;
    api_key?: string;
    is_active?: boolean;
    default_model_id?: string;
  }): Promise<AIProvider> {
    return (await http.post<AIProvider>("/api/ai/providers", payload)).data;
  },
  async testProvider(id: number): Promise<ProviderTestResult> {
    return (await http.post<ProviderTestResult>(`/api/ai/providers/${id}/test`)).data;
  },
  async deleteProvider(id: number): Promise<void> {
    await http.delete(`/api/ai/providers/${id}`);
  },
  async models(): Promise<AIModel[]> {
    return (await http.get<AIModel[]>("/api/ai/models")).data;
  },
  async createModel(payload: {
    provider_id: number;
    name: string;
    model_id: string;
    capability?: string;
  }): Promise<AIModel> {
    return (await http.post<AIModel>("/api/ai/models", payload)).data;
  },
  async updateModel(
    id: number,
    payload: { name?: string; model_id?: string; capability?: string; is_active?: boolean },
  ): Promise<AIModel> {
    return (await http.patch<AIModel>(`/api/ai/models/${id}`, payload)).data;
  },
  async deleteModel(id: number): Promise<void> {
    await http.delete(`/api/ai/models/${id}`);
  },

  // --- engines / styles ---
  async engines(): Promise<Engine[]> {
    return (await http.get<Engine[]>("/api/styles/engines")).data;
  },
  async styles(): Promise<VideoStyle[]> {
    return (await http.get<VideoStyle[]>("/api/styles")).data;
  },
  async createStyle(payload: Partial<VideoStyle>): Promise<VideoStyle> {
    return (await http.post<VideoStyle>("/api/styles", payload)).data;
  },
  async updateStyle(id: number, payload: Partial<VideoStyle>): Promise<VideoStyle> {
    return (await http.patch<VideoStyle>(`/api/styles/${id}`, payload)).data;
  },
  async setDefaultStyle(id: number): Promise<VideoStyle> {
    return (await http.post<VideoStyle>(`/api/styles/${id}/set-default`)).data;
  },

  // --- strategies（作者风格画像）---
  async strategies(activeOnly = false): Promise<ContentStrategy[]> {
    return (
      await http.get<ContentStrategy[]>("/api/strategies", {
        params: activeOnly ? { active_only: true } : undefined,
      })
    ).data;
  },
  async createStrategy(payload: StrategyPayload): Promise<ContentStrategy> {
    return (await http.post<ContentStrategy>("/api/strategies", payload)).data;
  },
  async updateStrategy(id: number, payload: StrategyPayload): Promise<ContentStrategy> {
    return (await http.patch<ContentStrategy>(`/api/strategies/${id}`, payload)).data;
  },
  async setDefaultStrategy(id: number): Promise<ContentStrategy> {
    return (await http.post<ContentStrategy>(`/api/strategies/${id}/set-default`)).data;
  },
  async deleteStrategy(id: number): Promise<void> {
    await http.delete(`/api/strategies/${id}`);
  },

  // --- projects ---
  async projects(params?: { status?: string; keyword?: string }): Promise<VideoProject[]> {
    return (await http.get<VideoProject[]>("/api/projects", { params })).data;
  },
  async project(id: number): Promise<VideoProjectDetail> {
    return (await http.get<VideoProjectDetail>(`/api/projects/${id}`)).data;
  },
  async createProject(payload: Record<string, unknown>): Promise<VideoProjectDetail> {
    return (await http.post<VideoProjectDetail>("/api/projects", payload)).data;
  },
  async regenerateProject(id: number, payload: Record<string, unknown>): Promise<VideoProjectDetail> {
    return (await http.post<VideoProjectDetail>(`/api/projects/${id}/regenerate`, payload)).data;
  },
  async approveProject(id: number): Promise<VideoProjectDetail> {
    return (await http.post<VideoProjectDetail>(`/api/projects/${id}/approve`)).data;
  },
  async deleteProject(id: number): Promise<void> {
    await http.delete(`/api/projects/${id}`);
  },

  // --- tasks ---
  async tasks(params?: { status?: string; resource_id?: number; limit?: number }): Promise<PipelineTask[]> {
    return (await http.get<PipelineTask[]>("/api/tasks", { params })).data;
  },
  async task(id: number): Promise<PipelineTask> {
    return (await http.get<PipelineTask>(`/api/tasks/${id}`)).data;
  },
  async taskEvents(id: number): Promise<PipelineEvent[]> {
    return (await http.get<PipelineEvent[]>(`/api/tasks/${id}/events`)).data;
  },
  async retryTask(id: number): Promise<PipelineTask> {
    return (await http.post<PipelineTask>(`/api/tasks/${id}/retry`)).data;
  },

  // --- outputs ---
  async outputs(params?: { engine?: string; status?: string }): Promise<RenderOutput[]> {
    return (await http.get<RenderOutput[]>("/api/outputs", { params })).data;
  },
  async output(id: number): Promise<RenderOutput> {
    return (await http.get<RenderOutput>(`/api/outputs/${id}`)).data;
  },
  async generateCover(outputId: number): Promise<RenderOutput> {
    return (await http.post<RenderOutput>(`/api/outputs/${outputId}/cover`)).data;
  },
  // --- AI 主题封面（全局独立配置）---
  async coverConfig(): Promise<CoverConfig> {
    return (await http.get<CoverConfig>("/api/cover/config")).data;
  },
  async saveCoverConfig(payload: {
    base_url: string;
    model: string;
    size: string;
    api_key?: string;
  }): Promise<CoverConfig> {
    return (await http.put<CoverConfig>("/api/cover/config", payload)).data;
  },
  async testCoverConfig(): Promise<{ ok: boolean; model: string; latency_ms: number }> {
    return (await http.post<{ ok: boolean; model: string; latency_ms: number }>("/api/cover/test")).data;
  },

  // --- transcriptions（视频/音频转文稿）---
  async transcriptions(): Promise<TranscriptionSummary[]> {
    return (await http.get<TranscriptionSummary[]>("/api/transcriptions")).data;
  },
  async transcription(id: number): Promise<TranscriptionJob> {
    return (await http.get<TranscriptionJob>(`/api/transcriptions/${id}`)).data;
  },
  async createTranscriptionUpload(
    file: File,
    language: string,
    title = "",
    onUploadProgress?: (percent: number) => void,
  ): Promise<TranscriptionSummary> {
    const form = new FormData();
    form.append("file", file);
    form.append("language", language);
    form.append("title", title);
    return (
      await http.post<TranscriptionSummary>("/api/transcriptions/upload", form, {
        onUploadProgress: (event) => {
          if (onUploadProgress && event.total) {
            onUploadProgress(Math.round((event.loaded / event.total) * 100));
          }
        },
      })
    ).data;
  },
  async createTranscriptionUrl(
    url: string,
    language: string,
    title = "",
  ): Promise<TranscriptionSummary> {
    return (
      await http.post<TranscriptionSummary>("/api/transcriptions/url", { url, language, title })
    ).data;
  },
  async deleteTranscription(id: number): Promise<void> {
    await http.delete(`/api/transcriptions/${id}`);
  },

  // --- runtime settings ---
  async getSettings(): Promise<{ render_concurrency: number; tts_rate: number }> {
    return (await http.get<{ render_concurrency: number; tts_rate: number }>("/api/settings")).data;
  },
  async updateSettings(payload: { render_concurrency: number; tts_rate?: number }): Promise<{ render_concurrency: number; tts_rate: number }> {
    return (await http.put<{ render_concurrency: number; tts_rate: number }>("/api/settings", payload)).data;
  },
};

export function outputFileUrl(id: number): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return `/api/outputs/${id}/file?token=${encodeURIComponent(token)}`;
}

export function projectStreamUrl(id: number): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return `/api/projects/${id}/stream?token=${encodeURIComponent(token)}`;
}

export function outputPosterUrl(id: number): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return `/api/outputs/${id}/poster?token=${encodeURIComponent(token)}`;
}

export function outputCoverUrl(id: number): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return `/api/outputs/${id}/cover?token=${encodeURIComponent(token)}`;
}

export function transcriptionFileUrl(id: number, format: "txt" | "srt"): string {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return `/api/transcriptions/${id}/file?format=${format}&token=${encodeURIComponent(token)}`;
}
