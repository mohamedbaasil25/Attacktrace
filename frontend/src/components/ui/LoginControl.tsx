import { LogIn, LogOut, User, UserCheck } from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../store/auth";
import { Button } from "./Button";

/** Operator login (Production Transition Roadmap, Phase 1): a compact icon that opens a popover,
 *  not an always-visible form (the form was removed from the top bar at the user's request --
 *  this restores the capability without reintroducing that always-on real estate). Only
 *  meaningful when the server has AT_AUTH_SECRET configured; without it, Isolate still works via
 *  the Operator-name field and a login attempt here just surfaces a clear "not configured" error.
 *  Closes on outside click or Escape, same pattern as AboutPopover. */
export function LoginControl() {
  const { token, username, role, pending, error, login, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (user && pass) void login(user, pass);
  };

  const signOut = () => {
    logout();
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        aria-label={token ? `Signed in as ${username}` : "Log in"}
        aria-expanded={open}
        className="h-8 min-h-0 w-8 p-0"
        onClick={() => setOpen((v) => !v)}
      >
        {token ? <UserCheck size={14} aria-hidden /> : <User size={14} aria-hidden />}
      </Button>
      {open && (
        <div
          role="dialog"
          aria-label={token ? "Account" : "Log in"}
          className="absolute right-0 top-8 z-20 w-56 rounded-md border border-line-2 bg-surface-2 p-3 text-label shadow-lg"
        >
          {token ? (
            <div className="flex flex-col gap-2">
              <p className="font-mono text-ink-1">{username}</p>
              <p className="text-caption text-ink-3">{role}</p>
              <Button variant="secondary" icon={<LogOut size={13} aria-hidden />} onClick={signOut}>
                Log out
              </Button>
            </div>
          ) : (
            <form onSubmit={submit} className="flex flex-col gap-2">
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder="Username"
                aria-label="Username"
                className="h-8 w-full rounded-sm border border-line-1 bg-transparent px-2 text-ink-1 placeholder:text-ink-3 focus:outline-none focus-visible:border-line-2"
              />
              <input
                value={pass}
                onChange={(e) => setPass(e.target.value)}
                placeholder="Password"
                type="password"
                aria-label="Password"
                className="h-8 w-full rounded-sm border border-line-1 bg-transparent px-2 text-ink-1 placeholder:text-ink-3 focus:outline-none focus-visible:border-line-2"
              />
              <Button
                type="submit"
                variant="primary"
                loading={pending}
                disabled={!user || !pass}
                icon={<LogIn size={13} aria-hidden />}
              >
                Log in
              </Button>
              {error && <p className="text-caption text-origin">{error}</p>}
            </form>
          )}
        </div>
      )}
    </div>
  );
}
