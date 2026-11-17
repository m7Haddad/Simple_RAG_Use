// Vector map (Lab mode): every chunk of a collection drawn as a dot on a 2D PCA projection.

import { Maximize2, Orbit } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type RefObject } from "react";
import { api, ApiError } from "../lib/api";
import { fmtInt } from "../lib/format";
import type { AssistantMessage, MapPoint, MapQueryPoint, VectorMapData } from "../lib/types";
import { ErrorNote, IconButton, Modal, Skeleton } from "./ui";

// Scatter plots can only keep 3 colours apart for every pair of dots; further sources share a gray.
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];
const OTHER = "var(--series-other)";
const HIT_RADIUS = 24; // px: the pointer only has to be this close to a dot, not on it
const TOOLTIP_W = 240; // px
const PAD = 22; // px of air around the plot so rings and rank labels are not clipped

interface Source {
  id: string;
  name: string;
  count: number;
  color: string;
}

/** Lab mode's vector map: every chunk as a dot, plus the inspected question and its retrieved chunks. */
export function VectorMapPanel({ collectionId, refreshKey, message }: { collectionId: string; refreshKey: string; message: AssistantMessage | null }) {
  const [data, setData] = useState<VectorMapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queryPoint, setQueryPoint] = useState<MapQueryPoint | null>(null);
  const [expanded, setExpanded] = useState(false);
  const queryCache = useRef(new Map<string, MapQueryPoint>());

  // Load the map, and reload it when the index changes. The old map stays on screen meanwhile.
  useEffect(() => {
    let cancelled = false;
    api
      .getMap(collectionId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load the vector map"));
    return () => {
      cancelled = true;
    };
  }, [collectionId, refreshKey]);

  // Place the inspected question (the query actually searched, after any rewrite) on the same map.
  const query = message?.sources?.query ?? null;
  useEffect(() => {
    if (!query || !data?.points.length) {
      setQueryPoint(null);
      return;
    }
    const key = `${data.index_version}|${data.points.length}|${query}`;
    const cached = queryCache.current.get(key);
    if (cached) {
      setQueryPoint(cached);
      return;
    }
    let cancelled = false;
    api
      .projectQuery(collectionId, query)
      .then((p) => {
        queryCache.current.set(key, p);
        if (!cancelled) setQueryPoint(p);
      })
      .catch(() => !cancelled && setQueryPoint(null));
    return () => {
      cancelled = true;
    };
  }, [collectionId, query, data]);

  const sources = useMemo(() => (data ? groupSources(data.points) : []), [data]);

  // Match the answer's chunks to dots by id AND text: ids are reused after a re-index.
  const retrieved = useMemo(() => {
    const ranks = new Map<number, number>();
    if (!data || !message?.sources) return ranks;
    const byId = new Map(data.points.map((p) => [p.chunk_id, p]));
    for (const c of message.sources.chunks) {
      const point = byId.get(c.chunk_id);
      if (point && c.text.startsWith(point.snippet)) ranks.set(c.chunk_id, c.rank);
    }
    return ranks;
  }, [data, message]);
  const outdated = !!message?.sources?.chunks.length && retrieved.size === 0;

  if (error && !data) return <ErrorNote className="m-4" message={error} />;
  if (!data) return <Skeleton className="m-4 h-80" />;
  if (!data.points.length) return <p className="p-4 text-sm text-muted">No chunks are indexed yet, so there is nothing to map.</p>;

  const plot = (big: boolean) => (
    <MapPlot points={data.points} sources={sources} retrieved={retrieved} query={message ? queryPoint : null} aspect={big ? 0.62 : 0.95} />
  );
  const kept = data.explained_variance.reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-sm font-semibold">Vector map</h3>
          <p className="text-xs text-muted">
            {fmtInt(data.points.length)} chunk vectors, {data.dimensions} numbers each, flattened to 2D with PCA.
          </p>
        </div>
        <IconButton label="Expand the map" onClick={() => setExpanded(true)}>
          <Maximize2 className="size-4" />
        </IconButton>
      </div>

      <Legend sources={sources} showQuery={!!message} />
      {plot(false)}
      <Caption explained={data.explained_variance} />

      {message && !message.sources && <p className="text-xs text-muted">Waiting for retrieval to place the question…</p>}
      {outdated && <p className="text-xs text-warn">This answer came from an older version of the index, so its chunks can&apos;t be highlighted here.</p>}

      <p className="rounded-lg bg-sunken px-3 py-2 text-xs leading-relaxed text-ink-2">
        <Orbit className="mr-1 inline size-3.5 align-[-2px] text-embed" />
        These two axes keep about <b className="font-medium">{Math.round(kept * 100)}%</b> of the spread between chunks. The rest is lost
        when 384 dimensions become 2, so dots that look close may not be close in the real space. The distances in the Inspector are the
        real numbers.
      </p>

      <PointsTable points={data.points} retrieved={retrieved} />

      <Modal open={expanded} onClose={() => setExpanded(false)} title="Vector map" width="max-w-5xl">
        <div className="space-y-3">
          <Legend sources={sources} showQuery={!!message} />
          {plot(true)}
          <Caption explained={data.explained_variance} />
        </div>
      </Modal>
    </div>
  );
}

/** One entry per source, in index order, so a source keeps its colour as others are added. */
function groupSources(points: MapPoint[]): Source[] {
  const firstId = new Map<string, number>();
  const counts = new Map<string, number>();
  const names = new Map<string, string>();
  for (const p of points) {
    const id = p.source_id ?? "unknown";
    firstId.set(id, Math.min(firstId.get(id) ?? Infinity, p.chunk_id));
    counts.set(id, (counts.get(id) ?? 0) + 1);
    names.set(id, p.source_name ?? "unknown source");
  }
  return [...firstId.keys()]
    .sort((a, b) => firstId.get(a)! - firstId.get(b)!)
    .map((id, i) => ({ id, name: names.get(id)!, count: counts.get(id)!, color: SERIES[i] ?? OTHER }));
}

// Legend: one swatch per coloured source, the rest folded into "Other sources", plus the question and retrieved markers.
function Legend({ sources, showQuery }: { sources: Source[]; showQuery: boolean }) {
  const named = sources.slice(0, SERIES.length);
  const others = sources.slice(SERIES.length);
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-2">
      {named.map((s) => (
        <li key={s.id} className="flex min-w-0 items-center gap-1.5" title={s.name}>
          <span className="size-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
          <span className="max-w-[16rem] truncate">{s.name}</span>
          <span className="font-mono text-[10px] text-muted">{s.count}</span>
        </li>
      ))}
      {others.length > 0 && (
        <li className="flex items-center gap-1.5" title={others.map((s) => s.name).join(", ")}>
          <span className="size-2.5 shrink-0 rounded-full" style={{ background: OTHER }} />
          <span>
            {others.length} other source{others.length === 1 ? "" : "s"}
          </span>
          <span className="font-mono text-[10px] text-muted">{others.reduce((n, s) => n + s.count, 0)}</span>
        </li>
      )}
      {showQuery && (
        <>
          <li className="flex items-center gap-1.5">
            <svg viewBox="-8 -8 16 16" className="size-3.5" aria-hidden>
              <path d={starPath(0, 0, 7)} fill="var(--ink)" />
            </svg>
            question
          </li>
          <li className="flex items-center gap-1.5">
            <span className="size-3 rounded-full border-[1.5px] border-ink" />
            retrieved (rank)
          </li>
        </>
      )}
    </ul>
  );
}

function Caption({ explained }: { explained: number[] }) {
  const pct = (v: number | undefined) => `${Math.round((v ?? 0) * 100)}%`;
  return (
    <p className="flex justify-between font-mono text-[10px] text-muted">
      <span>axis 1 → keeps {pct(explained[0])} of the spread</span>
      <span>axis 2 ↑ keeps {pct(explained[1])}</span>
    </p>
  );
}

// The scatter itself, drawn in screen pixels so dots stay the same size at any width.
function MapPlot({
  points,
  sources,
  retrieved,
  query,
  aspect,
}: {
  points: MapPoint[];
  sources: Source[];
  retrieved: Map<number, number>;
  query: MapQueryPoint | null;
  aspect: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const width = useElementWidth(box);
  const height = Math.round(width * aspect);
  const [hover, setHover] = useState<number | null>(null); // index into `screen`, or -1 for the question

  const colorOf = useMemo(() => new Map(sources.map((s) => [s.id, s.color])), [sources]);

  // Same scale on both axes, so distances on screen are not stretched in one direction.
  const screen = useMemo(() => {
    if (!width) return [];
    const xs = points.map((p) => p.x).concat(query ? [query.x] : []);
    const ys = points.map((p) => p.y).concat(query ? [query.y] : []);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const scale = Math.min((width - 2 * PAD) / (maxX - minX || 1), (height - 2 * PAD) / (maxY - minY || 1));
    const offX = (width - (maxX - minX) * scale) / 2;
    const offY = (height - (maxY - minY) * scale) / 2;
    const toScreen = (x: number, y: number) => ({ sx: offX + (x - minX) * scale, sy: height - (offY + (y - minY) * scale) });
    return [
      ...points.map((p) => ({ ...toScreen(p.x, p.y), point: p })),
      ...(query ? [{ ...toScreen(query.x, query.y), point: null }] : []),
    ];
  }, [points, query, width, height]);

  const dots = useMemo(() => screen.filter((s) => s.point) as { sx: number; sy: number; point: MapPoint }[], [screen]);
  const queryScreen = screen.find((s) => !s.point) ?? null;
  const highlighting = retrieved.size > 0 || !!query;

  // The heavy layer (every dot) only redraws when the data or size changes, not on hover.
  const dotLayer = useMemo(
    () =>
      dots
        .filter((d) => !retrieved.has(d.point.chunk_id))
        .map((d) => (
          <circle
            key={d.point.chunk_id}
            cx={d.sx}
            cy={d.sy}
            r={4}
            fill={colorOf.get(d.point.source_id ?? "unknown") ?? OTHER}
            stroke="var(--card)"
            strokeWidth={4}
            paintOrder="stroke"
            opacity={highlighting ? 0.35 : 1}
          />
        )),
    [dots, retrieved, colorOf, highlighting],
  );

  const hits = dots.filter((d) => retrieved.has(d.point.chunk_id)).sort((a, b) => retrieved.get(b.point.chunk_id)! - retrieved.get(a.point.chunk_id)!);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best = -2;
    let bestDist = HIT_RADIUS * HIT_RADIUS;
    screen.forEach((s, i) => {
      const d = (s.sx - mx) ** 2 + (s.sy - my) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = s.point ? i : -1;
      }
    });
    setHover(best === -2 ? null : best);
  };

  const hovered = hover === null ? null : hover === -1 ? queryScreen : screen[hover];

  return (
    <div ref={box} className="relative rounded-lg border border-line bg-card">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          className="block touch-none"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          role="img"
          aria-label={`Scatter plot of ${points.length} chunks${query ? ", with the question and its retrieved chunks highlighted" : ""}. A table view follows.`}
        >
          {dotLayer}

          {/* Leader lines from the question to each retrieved chunk. */}
          {queryScreen &&
            hits.map((d) => (
              <line key={`l${d.point.chunk_id}`} x1={queryScreen.sx} y1={queryScreen.sy} x2={d.sx} y2={d.sy} stroke="var(--ink-2)" strokeWidth={1} opacity={0.45} />
            ))}

          {hits.map((d) => (
            <g key={`h${d.point.chunk_id}`}>
              <circle cx={d.sx} cy={d.sy} r={6} fill={colorOf.get(d.point.source_id ?? "unknown") ?? OTHER} stroke="var(--card)" strokeWidth={4} paintOrder="stroke" />
              <circle cx={d.sx} cy={d.sy} r={8.5} fill="none" stroke="var(--ink)" strokeWidth={1.5} />
              <text x={d.sx + 10} y={d.sy - 8} className="fill-ink font-mono text-[10px] font-semibold" paintOrder="stroke" stroke="var(--card)" strokeWidth={3}>
                {retrieved.get(d.point.chunk_id)}
              </text>
            </g>
          ))}

          {queryScreen && (
            <path d={starPath(queryScreen.sx, queryScreen.sy, 9)} fill="var(--ink)" stroke="var(--card)" strokeWidth={4} paintOrder="stroke" strokeLinejoin="round" />
          )}

          {hovered && <circle cx={hovered.sx} cy={hovered.sy} r={11} fill="none" stroke="var(--accent)" strokeWidth={2} />}
        </svg>
      )}
      {!width && <div style={{ height: 240 }} />}

      {hovered && <Tooltip x={hovered.sx} y={hovered.sy} width={width} height={height} point={hovered.point} rank={hovered.point ? retrieved.get(hovered.point.chunk_id) : undefined} query={query} colorOf={colorOf} />}
    </div>
  );
}

function Tooltip({
  x,
  y,
  width,
  height,
  point,
  rank,
  query,
  colorOf,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  point: MapPoint | null;
  rank?: number;
  query: MapQueryPoint | null;
  colorOf: Map<string, string>;
}) {
  // Open on whichever side has room, and never past the plot's edges.
  const left = x + 14 + TOOLTIP_W <= width ? x + 14 : Math.max(0, Math.min(x - 14 - TOOLTIP_W, width - TOOLTIP_W));
  const above = y > height * 0.6;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg"
      style={{ width: TOOLTIP_W, left, ...(above ? { bottom: height - y + 14 } : { top: y + 14 }) }}
    >
      {point ? (
        <>
          {rank !== undefined && <div className="mb-1 font-mono text-[11px] font-semibold text-ink">retrieved · rank {rank}</div>}
          <div className="flex items-center gap-1.5 text-ink-2">
            <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: colorOf.get(point.source_id ?? "unknown") ?? OTHER }} />
            <span className="truncate font-medium">{point.source_name}</span>
          </div>
          <div className="mt-0.5 font-mono text-[10px] text-muted">
            {point.location}
            {point.heading ? ` · ${point.heading}` : ""} · chunk {point.chunk_id}
          </div>
          <p className="mt-1.5 line-clamp-4 text-ink-2">{point.snippet}</p>
        </>
      ) : (
        <>
          <div className="mb-1 font-mono text-[11px] font-semibold text-ink">your question</div>
          <p className="line-clamp-4 text-ink-2">{query?.query}</p>
        </>
      )}
    </div>
  );
}

// Table view: the same points without needing a mouse or colour vision.
function PointsTable({ points, retrieved }: { points: MapPoint[]; retrieved: Map<number, number> }) {
  return (
    <details className="rounded-lg border border-line bg-card text-xs">
      <summary className="cursor-pointer px-3 py-2 text-ink-2 select-none hover:text-ink">Show points as a table</summary>
      <div className="scroll-thin max-h-64 overflow-auto border-t border-line">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-sunken font-mono text-[10px] tracking-wider text-muted uppercase">
            <tr>
              <th className="px-2 py-1.5 font-medium">Chunk</th>
              <th className="px-2 py-1.5 font-medium">Source</th>
              <th className="px-2 py-1.5 text-right font-medium">x</th>
              <th className="px-2 py-1.5 text-right font-medium">y</th>
              <th className="px-2 py-1.5 text-right font-medium">Rank</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {points.map((p) => (
              <tr key={p.chunk_id} className={retrieved.has(p.chunk_id) ? "bg-accent-soft/50" : undefined}>
                <td className="px-2 py-1 font-mono tabular-nums">{p.chunk_id}</td>
                <td className="max-w-[10rem] truncate px-2 py-1" title={`${p.source_name} · ${p.location}`}>
                  {p.source_name} · {p.location}
                </td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{p.x.toFixed(3)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{p.y.toFixed(3)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{retrieved.get(p.chunk_id) ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function useElementWidth(ref: RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function starPath(cx: number, cy: number, r: number) {
  const pts = Array.from({ length: 10 }, (_, i) => {
    const radius = i % 2 === 0 ? r : r * 0.45;
    const angle = (Math.PI / 5) * i - Math.PI / 2;
    return `${(cx + radius * Math.cos(angle)).toFixed(2)},${(cy + radius * Math.sin(angle)).toFixed(2)}`;
  });
  return `M${pts.join("L")}Z`;
}
