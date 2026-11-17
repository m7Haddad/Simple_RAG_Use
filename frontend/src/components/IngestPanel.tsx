// Form for choosing the files and URLs to index.

import { FileText, Globe, Link2, Play, Trash2, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { fmtBytes } from "../lib/format";
import { Button, cx, ErrorNote, IconButton } from "./ui";

const ALLOWED = [".pdf", ".docx", ".txt", ".md", ".markdown"];
const MAX_FILE_MB = 25;
const MAX_SOURCES = 20;

function extensionOf(name: string) {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function validUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return "Only http:// and https:// links are supported";
    if (!url.hostname) return "The link has no host";
    return null;
  } catch {
    return "That does not look like a full URL (include https://)";
  }
}

export function IngestPanel({
  mode,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  mode: "create" | "add";
  busy: boolean;
  error: string | null;
  onSubmit: (input: { name: string; files: File[]; urls: string[] }) => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState<string[]>([]);
  const [urlDraft, setUrlDraft] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const addFiles = (incoming: FileList | File[]) => {
    const issues: string[] = [];
    const next = [...files];
    for (const file of Array.from(incoming)) {
      if (!ALLOWED.includes(extensionOf(file.name))) issues.push(`${file.name}: unsupported type (use ${ALLOWED.join(", ")})`);
      else if (file.size > MAX_FILE_MB * 1024 * 1024) issues.push(`${file.name}: larger than ${MAX_FILE_MB} MB`);
      else if (file.size === 0) issues.push(`${file.name}: file is empty`);
      else if (next.some((f) => f.name === file.name && f.size === file.size)) continue;
      else next.push(file);
    }
    if (next.length + urls.length > MAX_SOURCES) issues.push(`At most ${MAX_SOURCES} sources at a time`);
    setFiles(next.slice(0, MAX_SOURCES - urls.length));
    setProblems(issues);
  };

  const addUrl = () => {
    const value = urlDraft.trim();
    if (!value) return;
    const problem = validUrl(value);
    if (problem) return setProblems([problem]);
    if (urls.includes(value)) return setUrlDraft("");
    if (files.length + urls.length >= MAX_SOURCES) return setProblems([`At most ${MAX_SOURCES} sources at a time`]);
    setUrls([...urls, value]);
    setUrlDraft("");
    setProblems([]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const issues: string[] = [];
    if (mode === "create" && !name.trim()) issues.push("Give the knowledge base a name");
    if (urlDraft.trim()) issues.push("Press Add to include the URL you typed (or clear it)");
    if (!files.length && !urls.length) issues.push("Add at least one file or URL");
    setProblems(issues);
    if (!issues.length) onSubmit({ name: name.trim(), files, urls });
  };

  const total = files.length + urls.length;

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {mode === "create" && (
        <label className="block">
          <span className="mb-1.5 block font-mono text-[11px] tracking-widest text-muted uppercase">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            placeholder="e.g. Course notes"
            className="h-11 w-full rounded-lg border border-line bg-card px-3 text-[15px] outline-none placeholder:text-muted focus:border-accent"
          />
        </label>
      )}

      <div>
        <span className="mb-1.5 block font-mono text-[11px] tracking-widest text-muted uppercase">Files</span>
        <div
          role="button"
          tabIndex={0}
          onClick={() => picker.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), picker.current?.click())}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition",
            dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-card hover:border-accent/60",
          )}
        >
          <UploadCloud className={cx("size-7", dragging ? "text-accent" : "text-muted")} />
          <div className="text-sm">
            <span className="font-medium text-accent">Choose files</span> or drag them here
          </div>
          <div className="font-mono text-[11px] text-muted">PDF · DOCX · TXT · MD — up to {MAX_FILE_MB} MB each</div>
          <input
            ref={picker}
            type="file"
            multiple
            accept={ALLOWED.join(",")}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      <div>
        <span className="mb-1.5 block font-mono text-[11px] tracking-widest text-muted uppercase">Web pages</span>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Link2 className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <input
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addUrl())}
              placeholder="https://example.com/article"
              inputMode="url"
              className="h-10 w-full rounded-lg border border-line bg-card pr-3 pl-9 text-sm outline-none placeholder:text-muted focus:border-accent"
            />
          </div>
          <Button type="button" onClick={addUrl}>
            Add
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-muted">Public pages only; local and private network addresses are blocked for safety.</p>
      </div>

      {total > 0 && (
        <div className="rounded-xl border border-line bg-card">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="font-mono text-[11px] tracking-widest text-muted uppercase">{total} source{total === 1 ? "" : "s"} queued</span>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-muted hover:text-danger"
              onClick={() => {
                setFiles([]);
                setUrls([]);
              }}
            >
              <Trash2 className="size-3.5" /> Clear
            </button>
          </div>
          <ul className="scroll-thin max-h-56 divide-y divide-line overflow-y-auto">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-2.5 px-3 py-2 text-sm">
                <FileText className="size-4 shrink-0 text-load" />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="font-mono text-[11px] text-muted">{fmtBytes(f.size)}</span>
                <IconButton label={`Remove ${f.name}`} type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                  <X className="size-3.5" />
                </IconButton>
              </li>
            ))}
            {urls.map((u) => (
              <li key={u} className="flex items-center gap-2.5 px-3 py-2 text-sm">
                <Globe className="size-4 shrink-0 text-embed" />
                <span className="min-w-0 flex-1 truncate font-mono text-xs">{u}</span>
                <IconButton label={`Remove ${u}`} type="button" onClick={() => setUrls(urls.filter((x) => x !== u))}>
                  <X className="size-3.5" />
                </IconButton>
              </li>
            ))}
          </ul>
        </div>
      )}

      {problems.length > 0 && (
        <div role="alert" className="space-y-1 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">
          {problems.map((p) => (
            <div key={p}>{p}</div>
          ))}
        </div>
      )}
      {error && <ErrorNote message={error} />}

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" variant="primary" loading={busy} disabled={busy}>
          <Play className="size-4" /> {mode === "create" ? "Start indexing" : "Add & index"}
        </Button>
      </div>
    </form>
  );
}
