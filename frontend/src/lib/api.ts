/**
 * Cliente del backend.
 *
 * Dos formas de hablar con el servidor: peticiones normales y flujos de eventos
 * (SSE). El chat y la busqueda de precios usan lo segundo, porque las dos cosas
 * tardan y es mucho mejor mostrar el avance que un spinner.
 */

import type {
  AdminConfig,
  AdminStatus,
  ApiKeyCreated,
  ApiKeySummary,
  CapabilityGapSummary,
  Comparison,
  GeneratedToolDetail,
  GeneratedToolSummary,
  SavedItem,
  Status,
  StoreInfo,
  TelegramAgentApiSummary,
  TelegramAgentFileSummary,
  TelegramAgentSummary,
  TelegramTokenCreated,
} from "../types";

const TOKEN_KEY = "aw1-token";
const ADMIN_PASSWORD_KEY = "aw1-admin-password";

export class ApiError extends Error {
  status: number;
  requestId: string;
  constructor(message: string, status = 0, requestId = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(value: string): void {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* sin almacenamiento: el token dura lo que la pestana */
  }
}

export function getAdminPassword(): string {
  try {
    return localStorage.getItem(ADMIN_PASSWORD_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminPassword(value: string): void {
  try {
    if (value) localStorage.setItem(ADMIN_PASSWORD_KEY, value);
    else localStorage.removeItem(ADMIN_PASSWORD_KEY);
  } catch {
    /* sin almacenamiento: el password dura lo que la pestana */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("No hay conexion con el servidor de AW1.");
  }

  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  const payload = isJson ? await response.json().catch(() => ({})) : {};
  if (!response.ok) {
    throw new ApiError(
      payload.error ?? `El servidor respondio ${response.status}.`,
      response.status,
      payload.request_id ?? response.headers.get("x-request-id") ?? "",
    );
  }
  return payload as T;
}

/**
 * El panel admin (/api/admin/*) no usa el token general: exige su propia
 * password por separado, en la cabecera X-Admin-Password.
 */
async function adminRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  // FormData (subida de archivos) necesita que el navegador ponga su propio
  // Content-Type con el boundary -si se fuerza a JSON aca, el servidor no
  // puede parsear el multipart.
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const password = getAdminPassword();
  if (password) headers.set("X-Admin-Password", password);

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("No hay conexion con el servidor de AW1.");
  }

  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  const payload = isJson ? await response.json().catch(() => ({})) : {};
  if (!response.ok) {
    throw new ApiError(
      payload.error ?? `El servidor respondio ${response.status}.`,
      response.status,
      payload.request_id ?? response.headers.get("x-request-id") ?? "",
    );
  }
  return payload as T;
}

export interface StreamHandlers {
  onEvent: (type: string, data: any) => void;
  signal?: AbortSignal;
}

/**
 * Lee un flujo SSE emitido por el backend.
 *
 * Se usa fetch en vez de EventSource porque hace falta POST y cabecera de
 * autorizacion, y porque asi el mismo AbortSignal cancela la peticion.
 */
async function streamSSE(path: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: handlers.signal,
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.error ?? `El servidor respondio ${response.status}.`, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // El servidor separa las lineas con CRLF, que es lo que manda la
    // especificacion de SSE. Se normaliza a LF antes de partir por la linea en
    // blanco: buscar "\n\n" sobre un flujo con "\r\n\r\n" no encuentra nada y la
    // interfaz se queda esperando para siempre.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      let event = "message";
      const dataLines: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(dataLines.join("\n"));
      } catch {
        continue; // un evento ilegible no interrumpe el resto del flujo
      }
      // Un fallo pintando un evento no debe cortar el flujo, pero tampoco puede
      // desaparecer en silencio: eso deja la interfaz colgada sin ninguna pista.
      try {
        handlers.onEvent(event, payload);
      } catch (error) {
        console.error(`[aw1] fallo al procesar el evento "${event}"`, error);
      }
    }
  }
}

export const api = {
  status: () => request<Status>("/api/status"),

  chat: (
    body: { message: string; conversation_id?: string | null },
    handlers: StreamHandlers,
  ) => streamSSE("/api/chat", body, handlers),

  conversations: () => request<{ id: string; title: string; updated_at: string; messages: number }[]>(
    "/api/chat/conversations",
  ),
  conversation: (id: string) =>
    request<{ role: string; content: string; source: string; created_at: string }[]>(
      `/api/chat/${encodeURIComponent(id)}`,
    ),
  deleteConversation: (id: string) =>
    request<{ removed: number }>(`/api/chat/${encodeURIComponent(id)}`, { method: "DELETE" }),

  searchPrices: (
    body: { query: string; stores?: string[]; refresh?: boolean },
    handlers: StreamHandlers,
  ) => streamSSE("/api/prices/search", body, handlers),

  compare: (body: { query: string; stores?: string[]; refresh?: boolean }) =>
    request<Comparison>("/api/prices/compare", { method: "POST", body: JSON.stringify(body) }),

  stores: () => request<{ stores: StoreInfo[] }>("/api/prices/stores"),
  recentSearches: () =>
    request<{ searches: { id: number; query: string; created_at: string }[] }>("/api/prices/recent"),

  memory: () => request<{ items: SavedItem[]; total: number }>("/api/memory"),
  save: (body: { text: string; source?: string; kind?: string; meta?: Record<string, unknown> }) =>
    request<SavedItem>("/api/memory", { method: "POST", body: JSON.stringify(body) }),
  deleteItem: (id: number) => request<{ deleted: boolean }>(`/api/memory/${id}`, { method: "DELETE" }),
  purge: (everything: boolean) =>
    request<{ removed: Record<string, number> }>(`/api/memory?everything=${everything}`, {
      method: "DELETE",
    }),
};

export const admin = {
  status: () => adminRequest<AdminStatus>("/api/admin/status"),
  config: () => adminRequest<AdminConfig>("/api/admin/config"),
  setSecret: (name: string, value: string) =>
    adminRequest<AdminConfig>(`/api/admin/config/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  testSecret: (name: string, value: string) =>
    adminRequest<{ ok: boolean; detail: string }>(
      `/api/admin/config/${encodeURIComponent(name)}/test`,
      { method: "POST", body: JSON.stringify({ value }) },
    ),
  deleteSecret: (name: string) =>
    adminRequest<AdminConfig>(`/api/admin/config/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  apiKeys: () => adminRequest<ApiKeySummary[]>("/api/admin/api-keys"),
  createApiKey: (label: string) =>
    adminRequest<ApiKeyCreated>("/api/admin/api-keys", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),
  deleteApiKey: (id: number) =>
    adminRequest<void>(`/api/admin/api-keys/${id}`, { method: "DELETE" }),

  telegramAgents: () => adminRequest<TelegramAgentSummary[]>("/api/admin/telegram-agents"),
  telegramAgent: (id: string) =>
    adminRequest<TelegramAgentSummary>(`/api/admin/telegram-agents/${id}`),
  createTelegramAgent: (body: { label: string; system_prompt: string; bot_token: string }) =>
    adminRequest<TelegramAgentSummary>("/api/admin/telegram-agents", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateTelegramAgent: (
    id: string,
    body: { label: string; system_prompt: string; enabled: boolean },
  ) =>
    adminRequest<TelegramAgentSummary>(`/api/admin/telegram-agents/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteTelegramAgent: (id: string) =>
    adminRequest<void>(`/api/admin/telegram-agents/${id}`, { method: "DELETE" }),
  testTelegramToken: (value: string) =>
    adminRequest<{ ok: boolean; detail: string }>("/api/admin/telegram-agents/test-token", {
      method: "POST",
      body: JSON.stringify({ value }),
    }),
  createTelegramToken: (agentId: string, bot_token: string) =>
    adminRequest<TelegramTokenCreated>(`/api/admin/telegram-agents/${agentId}/tokens`, {
      method: "POST",
      body: JSON.stringify({ bot_token }),
    }),
  setTelegramTokenEnabled: (agentId: string, tokenId: string, enabled: boolean) =>
    adminRequest<TelegramTokenCreated>(
      `/api/admin/telegram-agents/${agentId}/tokens/${tokenId}`,
      { method: "PUT", body: JSON.stringify({ enabled }) },
    ),
  deleteTelegramToken: (agentId: string, tokenId: string) =>
    adminRequest<void>(`/api/admin/telegram-agents/${agentId}/tokens/${tokenId}`, {
      method: "DELETE",
    }),
  generatePrompt: (description: string) =>
    adminRequest<{ system_prompt: string }>("/api/admin/telegram-agents/generate-prompt", {
      method: "POST",
      body: JSON.stringify({ description }),
    }),
  humanizePrompt: (system_prompt: string) =>
    adminRequest<{ system_prompt: string }>("/api/admin/telegram-agents/humanize-prompt", {
      method: "POST",
      body: JSON.stringify({ system_prompt }),
    }),

  uploadTelegramAgentFile: (agentId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return adminRequest<TelegramAgentFileSummary>(`/api/admin/telegram-agents/${agentId}/files`, {
      method: "POST",
      body: form,
    });
  },
  deleteTelegramAgentFile: (agentId: string, fileId: string) =>
    adminRequest<void>(`/api/admin/telegram-agents/${agentId}/files/${fileId}`, {
      method: "DELETE",
    }),

  createTelegramAgentApi: (
    agentId: string,
    body: { name: string; description: string; url: string; method: string; headers: Record<string, string> },
  ) =>
    adminRequest<TelegramAgentApiSummary>(`/api/admin/telegram-agents/${agentId}/apis`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setTelegramAgentApiEnabled: (agentId: string, apiId: string, enabled: boolean) =>
    adminRequest<TelegramAgentApiSummary>(`/api/admin/telegram-agents/${agentId}/apis/${apiId}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  deleteTelegramAgentApi: (agentId: string, apiId: string) =>
    adminRequest<void>(`/api/admin/telegram-agents/${agentId}/apis/${apiId}`, {
      method: "DELETE",
    }),

  capabilityGaps: () => adminRequest<CapabilityGapSummary[]>("/api/admin/capability-gaps"),
  generatedTools: (agentId?: string) =>
    adminRequest<GeneratedToolSummary[]>(
      `/api/admin/generated-tools${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""}`,
    ),
  generatedTool: (toolId: string) =>
    adminRequest<GeneratedToolDetail>(`/api/admin/generated-tools/${toolId}`),
  createGeneratedTool: (body: {
    agent_id: string; name: string; description: string; source_gap_reasoning_id?: number | null;
  }) =>
    adminRequest<GeneratedToolDetail>("/api/admin/generated-tools", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateGeneratedToolCode: (toolId: string) =>
    adminRequest<GeneratedToolDetail>(`/api/admin/generated-tools/${toolId}/generate`, {
      method: "POST",
    }),
  testGeneratedTool: (toolId: string) =>
    adminRequest<GeneratedToolDetail>(`/api/admin/generated-tools/${toolId}/test`, {
      method: "POST",
    }),
  approveGeneratedTool: (toolId: string) =>
    adminRequest<GeneratedToolDetail>(`/api/admin/generated-tools/${toolId}/approve`, {
      method: "POST",
    }),
  rejectGeneratedTool: (toolId: string, reason = "") =>
    adminRequest<GeneratedToolDetail>(`/api/admin/generated-tools/${toolId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  deleteGeneratedTool: (toolId: string) =>
    adminRequest<void>(`/api/admin/generated-tools/${toolId}`, { method: "DELETE" }),
};
