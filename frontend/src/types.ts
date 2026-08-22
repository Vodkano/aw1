/** Contratos compartidos con el backend. */

export type Source = "local" | "wikipedia" | "gpt" | "system";

export interface Status {
  version: string;
  env: string;
  ollama: "online" | "offline";
  model: string;
  model_ready: boolean;
  models: string[];
  gpt_configured: boolean;
  database: string;
  auth_enabled: boolean;
  browser: { ready: boolean; headless: boolean; contexts: number; error: string };
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source?: Source;
  sources?: string[];
  streaming?: boolean;
  error?: boolean;
}

export interface Offer {
  store: string;
  store_slug: string;
  domain: string;
  url: string;
  title: string;
  price: number;
  currency: string;
  price_clp: number;
  price_label: string;
  in_stock: boolean | null;
  confidence: number;
  decided_by: "ia" | "heuristica";
  reason: string;
}

export type StoreStatus = "ok" | "vacio" | "error" | "timeout" | "pending" | "running";

export interface StoreOutcome {
  slug: string;
  name: string;
  search_url: string;
  cards_found: number;
  picked: number;
  offers: number;
  elapsed: number;
  status: StoreStatus;
  detail: string;
}

export interface SearchPlan {
  product: string;
  queries: string[];
  required: string[];
  forbidden: string[];
  notes: string;
}

export interface Comparison {
  query: string;
  product: string;
  offers: Offer[];
  verdict: string;
  stores: StoreOutcome[];
  visited: number;
  discarded: number;
  elapsed: number;
  from_cache: boolean;
  warnings: string[];
  ai: { llm_calls: number; llm_used: number; fallbacks: number; corrections: number; notes: string[] };
}

export interface SavedItem {
  id: number;
  text: string;
  source: string;
  kind: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface StoreInfo {
  slug: string;
  name: string;
  domain: string;
  country: string;
  currency: string;
  notes: string;
}

export interface AdminConfig {
  llm_provider: "ollama" | "groq";
  ollama_host: string;
  groq_configured: boolean;
  openai_configured: boolean;
}

export interface ApiKeySummary {
  id: number;
  label: string;
  key_preview: string;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeySummary {
  value: string;
}

export interface AdminStatus {
  llm_provider: string;
  llm_model: string;
  database: string;
  api_token_configured: boolean;
  api_keys_issued: number;
  conversations: number;
  messages: number;
  saved_items: number;
}
