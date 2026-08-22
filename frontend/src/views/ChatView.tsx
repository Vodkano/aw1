import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ArrowUp, Check, Copy, Bookmark, ExternalLink, Square, RotateCcw } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { Markdown } from "../components/Markdown";
import type { ChatMessage, Source, Status } from "../types";

const CONVERSATION_KEY = "aw1-conversation";

const SUGGESTIONS = [
  "Quien fue Violeta Parra",
  "Escribe una funcion en Python que valide un RUT",
  "Explicame que es un indice en SQL",
];

const SOURCE_LABEL: Record<Source, string> = {
  local: "Modelo local",
  wikipedia: "Wikipedia",
  gpt: "GPT",
  system: "Sistema",
};

function newId() {
  return Math.random().toString(36).slice(2);
}

export function ChatView({
  status,
  onSearchPrices,
}: {
  status: Status | null;
  onSearchPrices: (query: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversation, setConversation] = useState<string>(() => {
    try {
      return sessionStorage.getItem(CONVERSATION_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const remember = useCallback((id: string) => {
    setConversation(id);
    try {
      if (id) sessionStorage.setItem(CONVERSATION_KEY, id);
      else sessionStorage.removeItem(CONVERSATION_KEY);
    } catch {
      /* sin almacenamiento */
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const controller = new AbortController();
      abort.current = controller;
      setBusy(true);

      const assistantId = newId();
      setMessages((current) => [
        ...current,
        { id: newId(), role: "user" as const, content: text },
        { id: assistantId, role: "assistant" as const, content: "", streaming: true },
      ]);

      const patch = (changes: Partial<ChatMessage>) =>
        setMessages((current) =>
          current.map((item) => (item.id === assistantId ? { ...item, ...changes } : item)),
        );

      try {
        await api.chat(
          { message: text, conversation_id: conversation || null },
          {
            signal: controller.signal,
            onEvent: (type, data) => {
              switch (type) {
                case "start":
                  remember(data.conversation_id);
                  break;
                case "token":
                  setMessages((current) =>
                    current.map((item) =>
                      item.id === assistantId
                        ? { ...item, content: item.content + data.text }
                        : item,
                    ),
                  );
                  break;
                case "source":
                  setMessages((current) =>
                    current.map((item) =>
                      item.id === assistantId
                        ? { ...item, sources: [...(item.sources ?? []), data.url] }
                        : item,
                    ),
                  );
                  break;
                case "action":
                  if (data.kind === "search_prices") {
                    patch({ streaming: false });
                    setTimeout(() => onSearchPrices(data.query), 400);
                  }
                  break;
                case "notice":
                  setMessages((current) =>
                    current.map((item) =>
                      item.id === assistantId
                        ? { ...item, content: `${data.text}\n\n${item.content}` }
                        : item,
                    ),
                  );
                  break;
                case "done":
                  patch({ streaming: false, source: data.source, sources: data.sources });
                  remember(data.conversation_id);
                  break;
                case "error":
                  patch({ streaming: false, error: true, content: data.message, source: "system" });
                  break;
              }
            },
          },
        );
      } catch (error) {
        if ((error as Error).name === "AbortError") {
          patch({ streaming: false, content: "Respuesta cancelada." });
        } else {
          const detail = error instanceof ApiError && error.requestId ? ` (ref ${error.requestId})` : "";
          patch({
            streaming: false,
            error: true,
            source: "system",
            content: `${(error as Error).message}${detail}`,
          });
        }
      } finally {
        abort.current = null;
        setBusy(false);
        textarea.current?.focus();
      }
    },
    [conversation, onSearchPrices, remember],
  );

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    if (textarea.current) textarea.current.style.height = "auto";
    void send(text);
  };

  const reset = async () => {
    if (conversation) await api.deleteConversation(conversation).catch(() => undefined);
    remember("");
    setMessages([]);
  };

  const empty = messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-5 md:px-9">
        <div className={clsx("mx-auto max-w-3xl py-6", empty && "flex h-full flex-col")}>
          {empty ? (
            <div className="flex flex-1 flex-col justify-center pb-10">
              <h1 className="text-[26px] font-semibold tracking-tight md:text-[32px]">
                En que te ayudo?
              </h1>
              <p className="mt-2 max-w-lg text-[14.5px] muted">
                Charla simple va con Ollama. Codigo, analisis o tareas pesadas pasan a
                GPT solo si esta configurado -la etiqueta bajo cada respuesta dice cual
                se uso. Para precios uso un navegador real que entra a cada tienda.
              </p>
              <div className="mt-7 flex flex-wrap gap-2">
                {SUGGESTIONS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => void send(item)}
                    className="btn btn-ghost px-3 py-1.5 text-[13px] font-normal"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message) => (
                <Bubble key={message.id} message={message} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="px-5 pb-5 md:px-9 md:pb-7">
        <form onSubmit={submit} className="mx-auto max-w-3xl">
          <div className="card flex items-end gap-2 p-2 pl-4 transition-shadow focus-within:border-accent-500 focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-accent-500)_16%,transparent)]">
            <textarea
              ref={textarea}
              rows={1}
              value={draft}
              maxLength={4000}
              placeholder={
                status?.ollama === "online" ? "Escribe un mensaje…" : "Ollama no esta corriendo…"
              }
              onChange={(event) => {
                setDraft(event.target.value);
                const node = event.target;
                node.style.height = "auto";
                node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit(event);
                }
              }}
              className="max-h-44 min-h-9 flex-1 resize-none bg-transparent py-1.5 outline-none placeholder:text-ink-400"
            />
            {busy ? (
              <button
                type="button"
                onClick={() => abort.current?.abort()}
                className="btn btn-ghost size-9 shrink-0 p-0"
                aria-label="Detener"
              >
                <Square className="size-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                className="btn btn-primary size-9 shrink-0 p-0"
                aria-label="Enviar"
              >
                <ArrowUp className="size-4" strokeWidth={2.4} />
              </button>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between px-1 text-[11px] muted">
            <span>Enter envia · Shift + Enter salta de linea</span>
            {messages.length > 0 && (
              <button type="button" onClick={() => void reset()} className="inline-flex items-center gap-1 hover:text-[var(--text)]">
                <RotateCcw className="size-3" />
                Nueva conversacion
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-[16px] rounded-br-[6px] bg-accent-600 px-4 py-2.5 text-[14.5px] text-white">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-in-soft group">
      <div className="mb-1.5 flex items-center gap-2 text-[10.5px] uppercase tracking-[0.1em] muted">
        <span>AW1</span>
        {message.source && <span className="opacity-70">· {SOURCE_LABEL[message.source]}</span>}
      </div>

      <div className={clsx("text-[14.5px] leading-relaxed", message.error && "text-red-500")}>
        {message.content ? (
          <Markdown text={message.content} />
        ) : (
          <span className="inline-flex gap-1">
            {[0, 1, 2].map((index) => (
              <span
                key={index}
                className="size-1.5 animate-pulse-soft rounded-full bg-ink-400"
                style={{ animationDelay: `${index * 0.18}s` }}
              />
            ))}
          </span>
        )}
        {message.streaming && message.content && (
          <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-pulse-soft bg-accent-500" />
        )}
      </div>

      {!message.streaming && message.content && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {(message.sources ?? []).map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="chip hover:text-accent-600"
            >
              <ExternalLink className="size-3" />
              Fuente
            </a>
          ))}
          <button
            type="button"
            className="chip hover:text-[var(--text)]"
            onClick={async () => {
              await navigator.clipboard?.writeText(message.content).catch(() => undefined);
              setCopied(true);
              setTimeout(() => setCopied(false), 1400);
            }}
          >
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
            {copied ? "Copiado" : "Copiar"}
          </button>
          <button
            type="button"
            disabled={saved}
            className="chip hover:text-[var(--text)]"
            onClick={async () => {
              await api
                .save({ text: message.content, source: message.source ?? "local" })
                .catch(() => undefined);
              setSaved(true);
              window.dispatchEvent(new CustomEvent("aw1:memory"));
            }}
          >
            <Bookmark className={clsx("size-3", saved && "fill-current")} />
            {saved ? "Guardado" : "Guardar"}
          </button>
        </div>
      )}
    </div>
  );
}
