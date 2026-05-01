"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

const THEME_KEY = "edwinxu-agent.theme";

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyResolvedTheme(theme: "light" | "dark") {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
}

function resolveTheme(pref: ThemePreference): "light" | "dark" {
  if (pref === "system") return getSystemTheme();
  return pref;
}

type ThemeCtx = {
  preference: ThemePreference;
  resolved: "light" | "dark";
  setPreference: (p: ThemePreference) => void;
};

const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Default to light for MVP.
  const [preference, setPreferenceState] = useState<ThemePreference>("light");
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    try {
      const raw = localStorage.getItem(THEME_KEY);
      // MVP policy: default to light. If old value was "system", migrate to "light".
      if (raw === "dark" || raw === "light") setPreferenceState(raw);
      else if (raw === "system") setPreferenceState("light");
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    const nextResolved = resolveTheme(preference);
    setResolved(nextResolved);
    applyResolvedTheme(nextResolved);
    try {
      localStorage.setItem(THEME_KEY, preference);
    } catch {
      // ignore
    }
  }, [preference]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const handler = () => {
      if (preference !== "system") return;
      const nextResolved = resolveTheme("system");
      setResolved(nextResolved);
      applyResolvedTheme(nextResolved);
    };
    mql.addEventListener?.("change", handler);
    return () => mql.removeEventListener?.("change", handler);
  }, [preference]);

  const setPreference = useCallback((p: ThemePreference) => setPreferenceState(p), []);

  const value = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTheme must be used within ThemeProvider");
  return v;
}

