{% raw %}
import React, { useEffect, useState } from "react";

/*
 * Shared "Field Guide" chrome used across the starter pages: the breathing
 * background, the masthead, and a light/dark theme toggle.
 *
 * Theming is handled in main.css with CSS variables. By default the theme
 * follows the operating system (prefers-color-scheme). The toggle below sets an
 * explicit `light` / `dark` class on <html> to override that preference and
 * persists the choice to localStorage.
 */

const DOCS_URL = "https://github.com/piercefreeman/mountaineer#readme";
const GITHUB_URL = "https://github.com/piercefreeman/mountaineer";
const STORAGE_KEY = "mtn-theme";

type Theme = "light" | "dark";

export const Background = () => <div className="fg-bg" aria-hidden="true" />;

const MountainGlyph = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
    <path d="M2 20h20L14.7 6.5l-3.1 5.4-2.3-3.4L2 20Z" fill="var(--pine)" />
    <path d="M11.6 11.9 14.7 6.5l2.6 4.8-3 .7-2.7-.1Z" fill="var(--paper)" opacity="0.9" />
  </svg>
);

const ThemeToggle = () => {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") {
      document.documentElement.classList.add(stored);
      setTheme(stored);
    } else {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      setTheme(prefersDark ? "dark" : "light");
    }
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(next);
    window.localStorage.setItem(STORAGE_KEY, next);
    setTheme(next);
  };

  const isDark = theme === "dark";

  return (
    <button className="fg-toggle" onClick={toggle} aria-label="Toggle color theme" type="button">
      {isDark ? (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      ) : (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />
        </svg>
      )}
    </button>
  );
};

export const Masthead = ({ homeHref = "/" }: { homeHref?: string }) => (
  <>
    <header className="fg-mast">
      <a className="fg-brand" href={homeHref}>
        <span className="fg-glyph">
          <MountainGlyph />
        </span>
        <span>
          <p className="fg-name">Mountaineer</p>
          <span className="fg-sub">Typed from top to bottom</span>
        </span>
      </a>
      <nav className="fg-nav">
        <a href={DOCS_URL} target="_blank" rel="noreferrer">
          Docs
        </a>
        <a href={GITHUB_URL} target="_blank" rel="noreferrer">
          GitHub
        </a>
        <ThemeToggle />
      </nav>
    </header>
    <div className="fg-rule fg-strong" />
  </>
);
{% endraw %}
