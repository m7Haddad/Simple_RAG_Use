// Renders an answer as Markdown, with [n] citations shown as clickable chips.

import { isValidElement, memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CopyButton } from "./ui";

const CITATION = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\](?![(:])/g;

/** Turn "[1]" / "[1, 3]" into links we render as citation chips (fenced code is left alone). */
function linkCitations(markdown: string): string {
  return markdown
    .split(/(```[\s\S]*?(?:```|$))/g)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(CITATION, (_m, nums: string) =>
            nums
              .split(",")
              .map((n) => `[${n.trim()}](#cite-${n.trim()})`)
              .join(""),
          ),
    )
    .join("");
}

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

export const Markdown = memo(function Markdown({ text, onCite }: { text: string; onCite?: (n: number) => void }) {
  return (
    <div className="prose-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) {
              const n = Number(href.slice(6));
              return (
                <button
                  type="button"
                  onClick={() => onCite?.(n)}
                  className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded border border-accent/40 bg-accent-soft px-1 align-middle font-mono text-[10px] font-medium text-accent hover:bg-accent hover:text-accent-ink"
                  aria-label={`Show source ${n}`}
                >
                  {n}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
          pre: ({ children }) => {
            const code = textOf(children).replace(/\n$/, "");
            const lang = isValidElement<{ className?: string }>(children) ? children.props.className?.replace("language-", "") : undefined;
            return (
              <div className="overflow-hidden rounded-lg border border-line bg-sunken">
                <div className="flex items-center justify-between border-b border-line px-3 py-1">
                  <span className="font-mono text-[11px] text-muted">{lang ?? "code"}</span>
                  <CopyButton text={code} />
                </div>
                <pre className="scroll-thin overflow-x-auto p-3 font-mono text-[13px] leading-relaxed">{children}</pre>
              </div>
            );
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
});
