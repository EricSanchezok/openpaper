"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import {
  themeNames,
  type ColorScheme,
  type ColorSchemePreference,
  type ThemeName,
} from "@/design-system/generated/theme-metadata";

type ThemeContextValue = {
  theme: ThemeName;
  colorScheme: ColorScheme;
  preference: ColorSchemePreference;
  setTheme: (theme: ThemeName) => void;
  setColorSchemePreference: (preference: ColorSchemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function cookieValue(name: string) {
  if (typeof document === "undefined") return undefined;
  const prefix = `${name}=`;
  return document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(prefix))
    ?.slice(prefix.length);
}

function storedTheme(): ThemeName {
  if (typeof window === "undefined") return "default";
  const value =
    localStorage.getItem("scholens-theme") ?? cookieValue("scholens-theme");
  return themeNames.includes(value as ThemeName)
    ? (value as ThemeName)
    : "default";
}

function storedPreference(): ColorSchemePreference {
  if (typeof window === "undefined") return "system";
  const value =
    localStorage.getItem("scholens-color-scheme") ??
    cookieValue("scholens-color-scheme");
  return value === "light" || value === "dark" || value === "system"
    ? value
    : "system";
}

function subscribeToSystemScheme(onStoreChange: () => void) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", onStoreChange);
  return () => media.removeEventListener("change", onStoreChange);
}

export function ThemeProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [theme, setThemeState] = useState<ThemeName>(storedTheme);
  const [preference, setPreference] =
    useState<ColorSchemePreference>(storedPreference);
  const systemIsDark = useSyncExternalStore(
    subscribeToSystemScheme,
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    () => false,
  );
  const colorScheme: ColorScheme =
    preference === "system" ? (systemIsDark ? "dark" : "light") : preference;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.colorScheme = colorScheme;
    root.style.colorScheme = colorScheme;
  }, [colorScheme, theme]);

  const setTheme = useCallback((nextTheme: ThemeName) => {
    setThemeState(nextTheme);
    localStorage.setItem("scholens-theme", nextTheme);
    document.cookie = `scholens-theme=${nextTheme}; path=/; max-age=31536000; samesite=lax`;
  }, []);

  const setColorSchemePreference = useCallback(
    (nextPreference: ColorSchemePreference) => {
      setPreference(nextPreference);
      localStorage.setItem("scholens-color-scheme", nextPreference);
      document.cookie = `scholens-color-scheme=${nextPreference}; path=/; max-age=31536000; samesite=lax`;
    },
    [],
  );

  const value = useMemo(
    () => ({
      theme,
      colorScheme,
      preference,
      setTheme,
      setColorSchemePreference,
    }),
    [theme, colorScheme, preference, setTheme, setColorSchemePreference],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
