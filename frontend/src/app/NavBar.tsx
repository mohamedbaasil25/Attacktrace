import { Bot, Moon, Sun } from "lucide-react";
import { Logo } from "../components/ui/Logo";
import { AskAiDrawer } from "../features/ai-pilot/AskAiDrawer";
import { useUi } from "../store/ui";
import { NAV_ITEMS, normalizePath } from "./nav";

/** Shared top-level chrome for every page (Monitoring, Alerts, Assets, Investigations, Sources,
 *  Metrics, Local lab). Each page is a full browser navigation, not a client route, so "active"
 *  is just a string compare against the page's own current pathname -- no shared router state. */
export function NavBar() {
  const current = normalizePath(window.location.pathname);
  const askAiOpen = useUi((s) => s.askAiOpen);
  const setAskAiOpen = useUi((s) => s.setAskAiOpen);
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line-1 bg-surface-1 px-4">
      <div className="flex items-center gap-2.5 pr-3">
        <Logo size={28} />
        <div className="flex flex-col leading-none">
          <span className="font-sans text-[17px] font-semibold tracking-tight text-ink-1">
            Attack<span className="text-accent">Trace</span>
          </span>
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-3">
            Process security workspace
          </span>
        </div>
      </div>
      <div className="h-7 w-px shrink-0 bg-line-1" aria-hidden />
      <nav aria-label="Sections" className="flex h-full items-stretch gap-1">
        {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
          const active = current === path;
          return (
            <a
              key={path}
              href={path}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-1.5 border-b-2 px-2.5 text-label transition-colors duration-fast ease-out ${
                active
                  ? "border-accent text-ink-1"
                  : "border-transparent text-ink-3 hover:border-line-2 hover:text-ink-1"
              }`}
            >
              <Icon size={14} aria-hidden />
              {label}
            </a>
          );
        })}
      </nav>
      <button
        type="button"
        aria-pressed={theme === "light"}
        aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
        title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
        onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        className="ml-auto flex h-8 w-8 items-center justify-center rounded-sm text-ink-3 transition-colors duration-fast ease-out hover:text-ink-1"
      >
        {theme === "light" ? <Moon size={15} aria-hidden /> : <Sun size={15} aria-hidden />}
      </button>
      <button
        type="button"
        aria-pressed={askAiOpen}
        onClick={() => setAskAiOpen(!askAiOpen)}
        className="flex h-8 items-center gap-1.5 rounded-sm border border-accent/40 bg-accent-soft px-3 text-label font-medium text-accent transition-colors duration-fast ease-out hover:border-accent"
      >
        <Bot size={14} aria-hidden />
        Ask AI
      </button>
      <AskAiDrawer />
    </header>
  );
}
