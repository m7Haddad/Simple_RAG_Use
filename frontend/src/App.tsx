// App shell: the sidebar, the current view (a new knowledge base, or an existing one) and the settings drawer.

import { Menu as MenuIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CollectionView, type Tab } from "./components/CollectionView";
import { NewCollection } from "./components/NewCollection";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { Logo, Sidebar } from "./components/Sidebar";
import { Drawer, IconButton, Skeleton } from "./components/ui";
import { useCollections, useLlmHealth, useMediaQuery, useSettings, useTheme } from "./hooks";
import { useChatStore } from "./hooks/useChat";
import { api } from "./lib/api";
import type { JobStarted } from "./lib/types";

type View = { kind: "loading" } | { kind: "new" } | { kind: "collection"; id: string; tab: Tab };

function readFlag(key: string) {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export default function App() {
  const theme = useTheme();
  const llm = useLlmHealth();
  const { collections, error: collectionsError, refresh: refreshCollections, upsert } = useCollections();
  const settings = useSettings();
  const store = useChatStore();
  const desktop = useMediaQuery("(min-width: 1024px)");

  const [view, setView] = useState<View>({ kind: "loading" });
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const [labMode, setLabMode] = useState(() => readFlag("labMode"));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem("labMode", labMode ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  }, [labMode]);

  const pruneChats = store.prune;
  useEffect(() => {
    if (collections) pruneChats(collections.map((c) => c.id));
  }, [collections, pruneChats]);

  // Pick an initial view once the collections arrive; leave a deleted collection gracefully.
  useEffect(() => {
    if (!collections) {
      if (collectionsError && view.kind === "loading") setView({ kind: "new" });
      return;
    }
    if (view.kind === "loading") {
      setView(collections.length ? { kind: "collection", id: collections[0].id, tab: "chat" } : { kind: "new" });
    } else if (view.kind === "collection" && !collections.some((c) => c.id === view.id)) {
      setView({ kind: "new" });
    }
  }, [collections, collectionsError, view]);

  const refreshSettings = settings.refresh;
  const refreshAll = useCallback(() => {
    refreshCollections();
    refreshSettings();
  }, [refreshCollections, refreshSettings]);

  const trackJob = useCallback(
    (started: JobStarted, tab: Tab = "index") => {
      setJobs((j) => ({ ...j, [started.collection.id]: started.job.job_id }));
      upsert({ ...started.collection, active_job_id: started.job.job_id });
      setView({ kind: "collection", id: started.collection.id, tab });
      refreshCollections();
    },
    [refreshCollections, upsert],
  );

  const reindex = useCallback(
    async (id: string) => {
      const started = await api.reindex(id);
      setJobs((j) => ({ ...j, [id]: started.job.job_id }));
      refreshCollections();
    },
    [refreshCollections],
  );

  const select = (id: string) => {
    setView({ kind: "collection", id, tab: "chat" });
    setNavOpen(false);
  };

  const sidebar = (
    <Sidebar
      collections={collections}
      collectionsError={collectionsError}
      selectedId={view.kind === "collection" ? view.id : null}
      onSelect={select}
      onNew={() => {
        setView({ kind: "new" });
        setNavOpen(false);
      }}
      onOpenSettings={() => {
        setSettingsOpen(true);
        setNavOpen(false);
        settings.refresh();
      }}
      dark={theme.dark}
      onToggleTheme={theme.toggle}
      llm={llm}
    />
  );

  const current = view.kind === "collection" ? collections?.find((c) => c.id === view.id) : undefined;

  return (
    <div className="flex h-full">
      {desktop ? (
        <aside className="w-72 shrink-0 border-r border-line">{sidebar}</aside>
      ) : (
        <Drawer open={navOpen} onClose={() => setNavOpen(false)} title={<Logo />} side="left">
          <div className="-mx-5 -my-4 h-full">{sidebar}</div>
        </Drawer>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        {!desktop && (
          <div className="flex items-center gap-2 border-b border-line bg-panel px-3 py-2">
            <IconButton label="Open menu" onClick={() => setNavOpen(true)}>
              <MenuIcon className="size-5" />
            </IconButton>
            <Logo />
          </div>
        )}
        <div className="min-h-0 flex-1">
          {view.kind === "loading" && (
            <div className="mx-auto max-w-3xl space-y-4 p-8">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-4 w-96 max-w-full" />
              <Skeleton className="h-64" />
            </div>
          )}
          {view.kind === "new" && <NewCollection settings={settings.data} onStarted={(s) => trackJob(s)} />}
          {view.kind === "collection" && current && (
            <CollectionView
              key={current.id}
              summary={current}
              tab={view.tab}
              onTab={(tab) => setView({ kind: "collection", id: current.id, tab })}
              jobId={jobs[current.id] ?? current.active_job_id}
              onJobStarted={(s) => trackJob(s)}
              onChanged={refreshAll}
              onDeleted={() => {
                setView({ kind: "new" });
                refreshAll();
              }}
              onReindex={reindex}
              settings={settings.data?.settings ?? null}
              store={store}
              labMode={labMode}
              onLabMode={setLabMode}
            />
          )}
        </div>
      </main>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        data={settings.data}
        onSaved={(resp) => {
          settings.setData(resp);
          refreshCollections();
        }}
        collections={collections ?? []}
        jobs={jobs}
        onReindex={reindex}
        refresh={settings.refresh}
      />
    </div>
  );
}
