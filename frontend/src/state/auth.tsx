// Admin session: asks for the password when a protected action needs it.

import { KeyRound } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, ErrorNote, Modal } from "../components/ui";
import { api, ApiError } from "../lib/api";

interface AdminContext {
  /** Returns a valid admin token, asking for the password if needed. Null if the user cancels. */
  ensureToken: () => Promise<string | null>;
  /** Forget the token (for example after the server rejected it). */
  clear: () => void;
  isAuthenticated: boolean;
}

const Ctx = createContext<AdminContext | null>(null);

// The token lives only in this component's memory: never in localStorage or cookies.
export function AdminProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<{ value: string; expires: number } | null>(null);
  const [open, setOpen] = useState(false);
  const pending = useRef<((t: string | null) => void) | null>(null);

  useEffect(() => {
    if (!token) return;
    const timer = setTimeout(() => setToken(null), Math.max(0, token.expires - Date.now()));
    return () => clearTimeout(timer);
  }, [token]);

  const ensureToken = useCallback(() => {
    if (token && token.expires - Date.now() > 10_000) return Promise.resolve(token.value);
    return new Promise<string | null>((resolve) => {
      pending.current = resolve;
      setOpen(true);
    });
  }, [token]);

  const finish = (value: string | null) => {
    setOpen(false);
    pending.current?.(value);
    pending.current = null;
  };

  return (
    <Ctx.Provider value={{ ensureToken, clear: () => setToken(null), isAuthenticated: !!token }}>
      {children}
      <AdminLoginModal
        open={open}
        onCancel={() => finish(null)}
        onSuccess={(value, ttl) => {
          setToken({ value, expires: Date.now() + ttl * 1000 });
          finish(value);
        }}
      />
    </Ctx.Provider>
  );
}

export function useAdmin(): AdminContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAdmin must be used inside AdminProvider");
  return ctx;
}

function AdminLoginModal({ open, onCancel, onSuccess }: { open: boolean; onCancel: () => void; onSuccess: (token: string, ttl: number) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setPassword("");
      setError(null);
    }
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(password);
      setPassword("");
      onSuccess(result.token, result.expires_in);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onCancel} title="Admin password required">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-2">
          Changing settings needs the admin password. You stay signed in for 15 minutes; the session is kept in memory only.
        </p>
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium tracking-wide text-muted uppercase">Password</span>
          <div className="relative">
            <KeyRound className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <input
              type="password"
              autoFocus
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 w-full rounded-lg border border-line bg-card pr-3 pl-9 text-sm outline-none focus:border-accent"
            />
          </div>
        </label>
        {error && <ErrorNote message={error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!password}>
            Unlock
          </Button>
        </div>
      </form>
    </Modal>
  );
}
