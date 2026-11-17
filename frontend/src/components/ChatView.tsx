// The chat: messages, the composer, and the Lab mode side panel.

import { AlertTriangle, ArrowDown, ArrowUp, FlaskConical, MessageSquareText, Orbit, Sparkles, Square, Trash2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ChatStore } from "../hooks/useChat";
import { useMediaQuery } from "../hooks";
import { useChat } from "../hooks/useChat";
import { fmtMs } from "../lib/format";
import type { AssistantMessage, CollectionSummary, RagSettings } from "../lib/types";
import { Inspector } from "./Inspector";
import { Markdown } from "./Markdown";
import { SourcesList, type Highlight } from "./SourcesList";
import { Button, CopyButton, cx, Drawer, ErrorNote, IconButton } from "./ui";
import { VectorMapPanel } from "./VectorMap";

type LabTab = "inspector" | "map";

export function ChatView({
  collection,
  store,
  settings,
  labMode,
  onCloseLab,
  disabledReason,
}: {
  collection: CollectionSummary;
  store: ChatStore;
  settings: RagSettings | null;
  labMode: boolean;
  onCloseLab: () => void;
  disabledReason: string | null;
}) {
  const { messages, streaming, send, stop, clear } = useChat(collection.id, store, settings);
  const [inspectId, setInspectId] = useState<string | null>(null);
  const [labTab, setLabTab] = useState<LabTab>("inspector");
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const stickToBottom = useRef(true);
  const wide = useMediaQuery("(min-width: 1280px)");

  const assistants = messages.filter((m): m is AssistantMessage => m.role === "assistant");
  const inspected = assistants.find((m) => m.id === inspectId) ?? assistants[assistants.length - 1] ?? null;

  useEffect(() => setInspectId(null), [collection.id]);

  // Follow new tokens only while the reader is at the bottom; never yank them back up.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickToBottom.current = near;
    setAtBottom(near);
  };

  const scrollToBottom = () => {
    stickToBottom.current = true;
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  };

  const ask = (question: string) => {
    stickToBottom.current = true;
    setInspectId(null);
    send(question);
  };

  const labContent =
    labTab === "inspector" ? (
      <Inspector message={inspected} />
    ) : (
      <VectorMapPanel collectionId={collection.id} refreshKey={`${collection.updated_at}|${collection.chunk_count}`} message={inspected} />
    );

  return (
    <div className="flex h-full min-h-0">
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div ref={scroller} onScroll={onScroll} className="scroll-thin flex-1 overflow-y-auto" aria-live="polite">
          <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
            {messages.length === 0 ? (
              <EmptyChat name={collection.name} />
            ) : (
              <div className="space-y-6">
                {messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[15px] whitespace-pre-wrap text-bg">{m.content}</div>
                    </div>
                  ) : (
                    <AnswerBubble key={m.id} message={m} inspected={labMode && inspected?.id === m.id} onInspect={() => setInspectId(m.id)} />
                  ),
                )}
              </div>
            )}
          </div>
        </div>

        {!atBottom && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-28 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-card px-3 py-1.5 text-xs shadow-md hover:bg-sunken"
          >
            <ArrowDown className="size-3.5" /> Jump to latest
          </button>
        )}

        <Composer streaming={streaming} disabledReason={disabledReason} onSend={ask} onStop={stop} onClear={messages.length ? clear : undefined} />
      </div>

      {labMode && wide && (
        <aside aria-label="Pipeline Inspector" className="scroll-thin w-[420px] shrink-0 overflow-y-auto border-l border-line bg-bg">
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-line bg-bg/95 px-4 py-2.5 backdrop-blur">
            <LabTabs tab={labTab} onTab={setLabTab} />
            <span className="ml-auto font-mono text-[10px] tracking-widest text-muted uppercase">lab mode</span>
          </div>
          {labContent}
        </aside>
      )}
      {!wide && (
        <Drawer open={labMode} onClose={onCloseLab} title="Lab mode">
          <div className="-mx-5 -my-4">
            <div className="border-b border-line px-4 py-2">
              <LabTabs tab={labTab} onTab={setLabTab} />
            </div>
            {labContent}
          </div>
        </Drawer>
      )}
    </div>
  );
}

// Switch the Lab mode panel between the per-answer Inspector and the collection-wide vector map.
function LabTabs({ tab, onTab }: { tab: LabTab; onTab: (t: LabTab) => void }) {
  const tabs = [
    ["inspector", "Inspector", FlaskConical],
    ["map", "Vector map", Orbit],
  ] as const;
  return (
    <div role="tablist" aria-label="Lab mode views" className="flex gap-1">
      {tabs.map(([key, label, Icon]) => (
        <button
          key={key}
          role="tab"
          aria-selected={tab === key}
          onClick={() => onTab(key)}
          className={cx(
            "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition",
            tab === key ? "bg-accent-soft text-ink" : "text-muted hover:bg-sunken hover:text-ink",
          )}
        >
          <Icon className={cx("size-4", tab === key && "text-accent")} /> {label}
        </button>
      ))}
    </div>
  );
}

function EmptyChat({ name }: { name: string }) {
  return (
    <div className="mx-auto mt-10 max-w-lg text-center">
      <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        <MessageSquareText className="size-6" />
      </div>
      <h2 className="mt-4 font-display text-xl font-semibold">Ask {name}</h2>
      <p className="mt-2 text-sm text-ink-2">Answers come only from your documents. If the answer is not in the retrieved chunks, the model says it doesn&apos;t know.</p>
      <ul className="mt-6 space-y-2 text-left text-sm text-ink-2">
        <li className="flex gap-2.5 rounded-lg border border-line bg-card px-3 py-2.5">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-split" />
          <span>Ask about something specific: names, numbers, or a definition from your files.</span>
        </li>
        <li className="flex gap-2.5 rounded-lg border border-line bg-card px-3 py-2.5">
          <FlaskConical className="mt-0.5 size-4 shrink-0 text-embed" />
          <span>
            Turn on <b className="font-medium">Lab mode</b> to see the retrieved chunks, their distances and the exact prompt.
          </span>
        </li>
      </ul>
    </div>
  );
}

function AnswerBubble({ message, inspected, onInspect }: { message: AssistantMessage; inspected: boolean; onInspect: () => void }) {
  const [highlight, setHighlight] = useState<Highlight>(null);
  const chunks = message.sources?.chunks ?? [];
  const thinking = message.status === "streaming" && !message.content;
  return (
    <article className={cx("group rounded-2xl transition", inspected && "ring-1 ring-accent/40 ring-offset-8 ring-offset-bg")}>
      <div className="mb-1.5 flex items-center gap-2 font-mono text-[11px] text-muted">
        <span className="flex size-5 items-center justify-center rounded-md bg-ink text-[10px] font-bold text-bg">AI</span>
        {thinking && <span>{message.sources ? "generating…" : message.rewrite || !message.settings.rewrite ? "retrieving…" : "thinking…"}</span>}
        {message.status === "done" && message.timings?.total_ms !== undefined && <span>{fmtMs(message.timings.total_ms)}</span>}
        {message.status === "stopped" && <span className="text-warn">stopped</span>}
      </div>

      {message.notices.map((n) => (
        <div key={n} className="mb-2 flex items-start gap-1.5 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
          <AlertTriangle className="mt-px size-3.5 shrink-0" /> {n}
        </div>
      ))}

      {thinking ? (
        <div className="flex items-center gap-1.5 py-2" aria-label="Waiting for the answer">
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-1.5 animate-bounce rounded-full bg-muted" style={{ animationDelay: `${i * 120}ms` }} />
          ))}
        </div>
      ) : (
        message.content && (
          <div className={cx("text-[15px]", message.status === "streaming" && "caret")}>
            <Markdown text={message.content} onCite={(n) => setHighlight({ rank: n, nonce: Date.now() })} />
          </div>
        )
      )}

      {message.error && <ErrorNote className="mt-2" message={message.error.message} hint={message.error.hint} />}

      {chunks.length > 0 && <SourcesList chunks={chunks} highlight={highlight} />}

      {message.status !== "streaming" && (
        <div className="mt-2 flex items-center gap-1 opacity-70 transition group-hover:opacity-100">
          {message.content && <CopyButton text={message.content} label="Copy answer" />}
          {(message.sources || message.prompt) && (
            <button onClick={onInspect} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted hover:bg-sunken hover:text-ink">
              <FlaskConical className="size-3.5" /> Inspect
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function Composer({
  streaming,
  disabledReason,
  onSend,
  onStop,
  onClear,
}: {
  streaming: boolean;
  disabledReason: string | null;
  onSend: (q: string) => void;
  onStop: () => void;
  onClear?: () => void;
}) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = text.trim();
    if (!q || streaming || disabledReason) return;
    onSend(q);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-line bg-bg/90 px-4 pt-3 pb-4 backdrop-blur sm:px-6">
      <form onSubmit={submit} className="mx-auto max-w-3xl">
        {disabledReason && <p className="mb-2 text-xs text-warn">{disabledReason}</p>}
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-card p-2 shadow-sm focus-within:border-accent">
          {onClear && (
            <IconButton label="Clear conversation" type="button" onClick={onClear} disabled={streaming}>
              <Trash2 className="size-4" />
            </IconButton>
          )}
          <textarea
            ref={area}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={4000}
            disabled={!!disabledReason}
            placeholder={disabledReason ? "Chat unavailable" : "Ask a question about your documents…"}
            aria-label="Question"
            className="max-h-[200px] min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted focus-visible:outline-none disabled:cursor-not-allowed"
          />
          {streaming ? (
            <Button type="button" variant="secondary" onClick={onStop} className="h-9 shrink-0 px-3" aria-label="Stop generating">
              <Square className="size-3.5 fill-current" /> Stop
            </Button>
          ) : (
            <Button type="submit" variant="primary" size="icon" disabled={!text.trim() || !!disabledReason} aria-label="Send">
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>
        <p className="mt-1.5 text-center font-mono text-[10px] text-muted">Enter to send · Shift+Enter for a new line</p>
      </form>
    </div>
  );
}
