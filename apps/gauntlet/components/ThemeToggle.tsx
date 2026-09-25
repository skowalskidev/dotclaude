"use client";
// OWNED BY SLICE `shell`. Toggles document.documentElement.dataset.theme between dark/light, persists to localStorage 'gauntlet-theme'.
import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "dark" | "light";
function readTheme(): Theme { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; }
function subscribeTheme(cb: () => void) {
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => mo.disconnect();
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => "dark" as Theme);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("gauntlet-theme", next);
    } catch {
      /* storage unavailable */
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle theme"
      title="Toggle theme"
      className="inline-flex items-center justify-center rounded-md p-1.5 hover:bg-sf2"
    >
      {theme === "dark" ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}
