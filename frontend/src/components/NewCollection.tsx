// The "New knowledge base" page.

import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { JobStarted, SettingsResponse } from "../lib/types";
import { IngestPanel } from "./IngestPanel";
import { cx } from "./ui";

const STEPS = [
  { n: 1, name: "Load", color: "text-load border-load/40", text: "Text is extracted one page (PDF) or section (DOCX, Markdown, web page) at a time, so every answer can cite a page." },
  { n: 2, name: "Split", color: "text-split border-split/40", text: "Each page is cut into overlapping chunks, preferring paragraph and sentence boundaries." },
  { n: 3, name: "Embed", color: "text-embed border-embed/40", text: "A local model turns each chunk into a vector. Nothing leaves your machine for this step." },
  { n: 4, name: "Index", color: "text-index border-index/40", text: "Vectors are stored in Chroma on disk. Restarting the app reloads them instead of re-embedding." },
];

export function NewCollection({ settings, onStarted }: { settings: SettingsResponse | null; onStarted: (started: JobStarted) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section>
          <h1 className="font-display text-2xl font-semibold tracking-tight">New knowledge base</h1>
          <p className="mt-1 text-sm text-ink-2">Add documents and web pages. You will watch them move through the pipeline live.</p>
          <div className="mt-6 rounded-2xl border border-line bg-card p-5 sm:p-6">
            <IngestPanel
              mode="create"
              busy={busy}
              error={error}
              onSubmit={async ({ name, files, urls }) => {
                setBusy(true);
                setError(null);
                try {
                  onStarted(await api.createCollection(name, files, urls));
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : "Could not start ingestion");
                } finally {
                  setBusy(false);
                }
              }}
            />
          </div>
        </section>

        <aside className="lg:pt-[68px]">
          <div className="lab-grid rounded-2xl border border-line bg-panel p-5">
            <h2 className="font-mono text-[11px] tracking-widest text-muted uppercase">What happens next</h2>
            <ol className="mt-4 space-y-4">
              {STEPS.map((s) => (
                <li key={s.n} className="flex gap-3">
                  <span className={cx("flex size-7 shrink-0 items-center justify-center rounded-full border-2 bg-card font-mono text-xs font-semibold", s.color)}>{s.n}</span>
                  <div>
                    <div className="font-display text-sm font-semibold">{s.name}</div>
                    <p className="text-xs leading-relaxed text-ink-2">{s.text}</p>
                  </div>
                </li>
              ))}
            </ol>
            {settings && (
              <dl className="mt-5 grid grid-cols-2 gap-2 border-t border-line pt-4 font-mono text-[11px]">
                <dt className="text-muted">chunk size</dt>
                <dd className="text-right">{settings.settings.chunk_size} chars</dd>
                <dt className="text-muted">overlap</dt>
                <dd className="text-right">{settings.settings.chunk_overlap} chars</dd>
                <dt className="text-muted">headings</dt>
                <dd className="text-right">{settings.settings.heading_aware_chunking ? "aware" : "off"}</dd>
                <dt className="text-muted">embedder</dt>
                <dd className="truncate text-right" title={settings.embedding_model}>
                  {settings.embedding_model.split("/").pop()}
                </dd>
              </dl>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
