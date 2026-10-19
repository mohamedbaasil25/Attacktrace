import { LogIn, LogOut } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import { useAuth } from "../../store/auth";

/** Operator login (Production Transition Roadmap, Phase 1): only meaningful when the server has
 *  AT_AUTH_SECRET configured -- without it /api/isolate falls back to trusting the Operator-name
 *  field, and a login attempt here just gets a clear "not configured" error. */
export function LoginControl() {
  const { token, username, role, pending, error, login, logout } = useAuth();
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");

  if (token) {
    return (
      <div className="flex h-8 items-center gap-1.5 rounded-sm border border-line-1 px-2 text-ink-3">
        <span className="font-mono text-ink-1">{username}</span>
        <span className="text-ink-3">({role})</span>
        <button
          type="button"
          onClick={logout}
          aria-label="Log out"
          title="Log out"
          className="ml-1 text-ink-3 hover:text-ink-1"
        >
          <LogOut size={13} aria-hidden />
        </button>
      </div>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (user && pass) void login(user, pass);
  };

  return (
    <form onSubmit={submit} className="flex items-center gap-1">
      <input
        value={user}
        onChange={(e) => setUser(e.target.value)}
        placeholder="Username"
        aria-label="Username"
        className="h-8 w-20 rounded-sm border border-line-1 bg-transparent px-2 text-ink-1 placeholder:text-ink-3 focus:outline-none focus-visible:border-line-2"
      />
      <input
        value={pass}
        onChange={(e) => setPass(e.target.value)}
        placeholder="Password"
        type="password"
        aria-label="Password"
        className="h-8 w-20 rounded-sm border border-line-1 bg-transparent px-2 text-ink-1 placeholder:text-ink-3 focus:outline-none focus-visible:border-line-2"
      />
      <button
        type="submit"
        disabled={pending || !user || !pass}
        title={error ?? "Log in"}
        className="flex h-8 items-center gap-1 rounded-sm border border-line-1 px-2 text-ink-2 transition-colors duration-fast ease-out hover:text-ink-1 disabled:opacity-50"
      >
        <LogIn size={13} aria-hidden />
      </button>
      {error && <span className="text-caption text-origin">{error}</span>}
    </form>
  );
}
