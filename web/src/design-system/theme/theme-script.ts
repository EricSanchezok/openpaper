export const themeInitializationScript = `
(() => {
  const root = document.documentElement;
  const cookies = Object.fromEntries(document.cookie.split("; ").filter(Boolean).map((entry) => {
    const separator = entry.indexOf("=");
    return separator < 0 ? [entry, ""] : [entry.slice(0, separator), entry.slice(separator + 1)];
  }));
  const themePreference = localStorage.getItem("scholens-theme") || cookies["scholens-theme"];
  const storedTheme = ["default"].includes(themePreference) ? themePreference : "default";
  const schemePreference = localStorage.getItem("scholens-color-scheme") || cookies["scholens-color-scheme"];
  const storedScheme = ["system", "light", "dark"].includes(schemePreference) ? schemePreference : "system";
  const scheme = storedScheme === "system"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : storedScheme;
  root.dataset.theme = storedTheme;
  root.dataset.colorScheme = scheme;
  root.style.colorScheme = scheme;
})();`;
