import { Bot, FileX, LoaderCircle, Lock, Send, User, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getIncidents, postAskAi } from "../../lib/api";
import type { Incident } from "../../lib/types";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { OriginCard } from "../incident/OriginCard";

type Load =
  | { state: "loading" }
  | { state: "unauthorized" }
  | { state: "error" }
  | { state: "ready"; incidents: Incident[] };

const ACTIVE = new Set(["localizing", "open", "contained"]);

interface ChatMessage {
  id: number;
  role: "user" | "ai";
  text: string;
  tone: "normal" | "error";
}

/** One line of real-time context, so the operator sees what's active before asking about it --
 *  the model gets the same incidents (minus ground_truth) from the backend, not this string. */
function summaryLine(i: Incident): string {
  const top = i.origin[0];
  const statusLine =
    i.status === "closed"
      ? "Closed"
      : i.status === "contained"
        ? `Contained${i.isolated_by ? ` by ${i.isolated_by}` : ""}`
        : "Active";
  return `${statusLine} · ${i.id} · origin ${top?.id ?? "unresolved"}${
    top ? ` (${Math.round(top.confidence * 100)}%)` : ""
  }`;
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 503) return "Ask AI isn't configured on this server (AT_AI_API_KEY is not set).";
    if (e.status === 429) return "Too many questions in a row -- wait a moment and try again.";
    if (e.status === 401) return "Login required to use Ask AI.";
    if (e.status === 502) return "The model request failed. Try again.";
    return e.message;
  }
  return "Something went wrong. Try again.";
}

function Bubble({ m }: { m: ChatMessage }) {
  const ai = m.role === "ai";
  return (
    <div className={`flex items-start gap-2 ${ai ? "" : "flex-row-reverse"}`}>
      <div
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
          ai ? "bg-accent-soft text-accent" : "bg-surface-2 text-ink-2"
        }`}
      >
        {ai ? <Bot size={13} aria-hidden /> : <User size={13} aria-hidden />}
      </div>
      <p
        className={`max-w-[85%] whitespace-pre-wrap rounded-md px-3 py-2 text-label leading-relaxed ${
          m.tone === "error"
            ? "border border-origin/40 bg-origin/10 text-origin"
            : ai
              ? "bg-surface-2 text-ink-1"
              : "bg-accent-soft text-ink-1"
        }`}
      >
        {m.text}
      </p>
    </div>
  );
}

let msgId = 0;

/** Ask AI's global slide-over: one `NavBar` instance renders this per page (every page gets
 *  NavBar), and any other component on that same page can open it through `useUi`'s
 *  `askAiOpen`/`setAskAiOpen` (e.g. the Incident panel's own "Ask AI" button) without prop
 *  drilling. Incident data is fetched lazily, only once the drawer is actually opened. */
export function AskAiDrawer() {
  const open = useUi((s) => s.askAiOpen);
  const close = () => useUi.getState().setAskAiOpen(false);
  const authToken = useAuth((s) => s.token);

  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoad({ state: "loading" });
    getIncidents(authToken || undefined)
      .then((incidents) => live && setLoad({ state: "ready", incidents }))
      .catch((e: unknown) => {
        if (!live) return;
        const status = e instanceof ApiError ? e.status : 0;
        setLoad({ state: status === 401 ? "unauthorized" : "error" });
      });
    return () => {
      live = false;
    };
  }, [open, authToken]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, pending]);

  const focus = useMemo(() => {
    if (load.state !== "ready") return null;
    return load.incidents.find((i) => ACTIVE.has(i.status)) ?? load.incidents[0] ?? null;
  }, [load]);

  const ask = async (): Promise<void> => {
    const q = question.trim();
    if (!q || pending) return;
    setQuestion("");
    setMessages((m) => [...m, { id: ++msgId, role: "user", text: q, tone: "normal" }]);
    setPending(true);
    try {
      const { answer } = await postAskAi(q, authToken || undefined);
      setMessages((m) => [...m, { id: ++msgId, role: "ai", text: answer, tone: "normal" }]);
    } catch (e) {
      setMessages((m) => [...m, { id: ++msgId, role: "ai", text: errorText(e), tone: "error" }]);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <div
        aria-hidden={!open}
        onClick={close}
        className={`fixed inset-0 z-40 bg-surface-0/60 transition-opacity duration-fast ease-out ${
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-label="Ask AI"
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line-1 bg-surface-1 shadow-xl transition-transform duration-slow ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line-1 px-3">
          <Bot size={16} className="text-accent" aria-hidden />
          <h2 className="text-sm font-semibold tracking-tight text-ink-1">Ask AI</h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close Ask AI"
            className="ml-auto flex h-8 w-8 items-center justify-center rounded-sm text-ink-3 transition-colors duration-fast ease-out hover:text-ink-1"
          >
            <X size={16} aria-hidden />
          </button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
          {load.state === "loading" && <LoaderCircle size={16} className="animate-spin text-ink-3" aria-hidden />}
          {load.state === "unauthorized" && (
            <div className="flex items-center gap-1 text-caption text-ink-3">
              <Lock size={12} aria-hidden />
              Login required
            </div>
          )}
          {load.state === "error" && (
            <div className="flex items-center gap-1 text-caption text-ink-3">
              <FileX size={12} aria-hidden />
              Could not load current incidents
            </div>
          )}
          {focus && (
            <div className="flex flex-col gap-2 rounded-md border border-line-1 bg-surface-0 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-ink-3">
                  Current focus
                </span>
                <a
                  href={`/investigations?id=${encodeURIComponent(focus.id)}`}
                  className="shrink-0 text-caption text-ink-3 transition-colors duration-fast ease-out hover:text-ink-1"
                >
                  Full investigation →
                </a>
              </div>
              <span className="truncate font-mono text-caption text-ink-1">{summaryLine(focus)}</span>
              <OriginCard incident={focus} />
            </div>
          )}
          {load.state === "ready" && !focus && (
            <p className="font-mono text-caption text-ink-3">No incidents yet.</p>
          )}
          <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
            {messages.length === 0 && (
              <p className="font-mono text-caption text-ink-3">
                Ask about the current incident -- origin, confidence, propagation path, or what to
                do next.
              </p>
            )}
            {messages.map((m) => (
              <Bubble key={m.id} m={m} />
            ))}
            {pending && (
              <div className="flex items-center gap-2 text-ink-3">
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
                <span className="font-mono text-caption">Thinking…</span>
              </div>
            )}
          </div>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
          className="flex items-center gap-2 border-t border-line-1 p-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this incident"
            aria-label="Ask AI a question"
            disabled={pending}
            className="h-9 flex-1 rounded-sm border border-line-1 bg-surface-0 px-3 text-label text-ink-1 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={pending || !question.trim()}
            className="flex h-9 items-center gap-1 rounded-sm bg-accent px-3 text-label font-medium text-bg transition-opacity duration-fast ease-out hover:opacity-90 disabled:opacity-50"
          >
            <Send size={14} aria-hidden />
            Ask
          </button>
        </form>
      </aside>
    </>
  );
}
