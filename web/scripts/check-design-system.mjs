import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const webRoot = path.resolve(import.meta.dirname, "..");
const sourceRoot = path.join(webRoot, "src");
const tokenRoot = path.join(sourceRoot, "design-system", "tokens");
const generatedRoot = path.join(sourceRoot, "design-system", "generated");

const readJson = async (filePath) =>
  JSON.parse(await readFile(filePath, "utf8"));

function flattenTokens(value, prefix = [], tokens = new Map()) {
  for (const [name, child] of Object.entries(value)) {
    const tokenPath = [...prefix, name];
    if (child && typeof child === "object" && "$value" in child) {
      tokens.set(tokenPath.join("."), child);
    } else if (child && typeof child === "object") {
      flattenTokens(child, tokenPath, tokens);
    }
  }
  return tokens;
}

function reference(value) {
  return typeof value === "string" ? value.match(/^\{([^}]+)\}$/)?.[1] : null;
}

async function collectFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await collectFiles(entryPath)));
    else files.push(entryPath);
  }
  return files;
}

function lineNumber(contents, index) {
  return contents.slice(0, index).split("\n").length;
}

const violations = [];
const report = (message) => violations.push(message);

const primitives = flattenTokens(
  await readJson(path.join(tokenRoot, "primitives.json")),
);
const palette = flattenTokens(
  await readJson(path.join(tokenRoot, "themes", "default.json")),
);
const dimensions = flattenTokens(
  await readJson(path.join(tokenRoot, "dimensions.json")),
);
const effects = flattenTokens(
  await readJson(path.join(tokenRoot, "effects.json")),
);
const light = flattenTokens(
  await readJson(path.join(tokenRoot, "semantic", "light.json")),
);
const dark = flattenTokens(
  await readJson(path.join(tokenRoot, "semantic", "dark.json")),
);

for (const [tokenPath, token] of palette) {
  const target = reference(token.$value);
  if (!target?.startsWith("primitive.")) {
    report(
      `${tokenPath}: theme palette values must reference primitive.* directly`,
    );
  } else if (!primitives.has(target)) {
    report(`${tokenPath}: unresolved primitive reference ${target}`);
  }
}

const lightPaths = [...light.keys()].sort();
const darkPaths = [...dark.keys()].sort();
for (const tokenPath of new Set([...lightPaths, ...darkPaths])) {
  const lightToken = light.get(tokenPath);
  const darkToken = dark.get(tokenPath);
  if (!lightToken || !darkToken) {
    report(`${tokenPath}: semantic token must exist in both Light and Dark`);
    continue;
  }
  if (lightToken.$type !== darkToken.$type) {
    report(`${tokenPath}: Light/Dark token types do not match`);
  }
  for (const [appearance, token] of [
    ["Light", lightToken],
    ["Dark", darkToken],
  ]) {
    const target = reference(token.$value);
    if (!target?.startsWith("palette.")) {
      report(`${tokenPath}: ${appearance} must reference palette.* directly`);
    } else if (!palette.has(target)) {
      report(`${tokenPath}: ${appearance} has unresolved reference ${target}`);
    }
  }
}

const adapterPath = path.join(
  sourceRoot,
  "design-system",
  "adapters",
  "tailwind.json",
);
const adapter = await readJson(adapterPath);
for (const [group, aliases] of Object.entries(adapter)) {
  for (const [name, target] of Object.entries(aliases)) {
    const valid =
      (light.has(target) && dark.has(target)) ||
      dimensions.has(target) ||
      effects.has(target);
    if (!valid) report(`tailwind ${group}.${name}: unresolved token ${target}`);
    const namespace =
      group === "colors" ? "color" : group === "fontSizes" ? "text" : "shadow";
    if (`${namespace}-${name}` === target.replaceAll(".", "-")) {
      report(
        `tailwind ${group}.${name}: alias would create a self-referencing CSS variable`,
      );
    }
  }
}

for (const [tokenPath, token] of effects) {
  if (token.$type !== "shadow") {
    report(`${tokenPath}: effect tokens must use the DTCG shadow type`);
  }
  const colorTarget = reference(token.$value?.color);
  if (!colorTarget || !light.has(colorTarget) || !dark.has(colorTarget)) {
    report(
      `${tokenPath}: shadow color must resolve to a Light/Dark semantic token`,
    );
  }
}

const globalsPath = path.join(sourceRoot, "styles", "globals.css");
const globals = await readFile(globalsPath, "utf8");
const generatedFoundation = await readFile(
  path.join(generatedRoot, "dimensions.css"),
  "utf8",
);
if (!generatedFoundation.includes("@theme inline")) {
  report(
    "src/design-system/generated/dimensions.css: Tailwind adapter was not generated",
  );
}
if (globals.includes("@theme")) {
  report(
    "src/styles/globals.css: @theme aliases are generated; do not maintain them here",
  );
}

const scanRoots = [sourceRoot, path.join(webRoot, ".storybook")];
const scannedFiles = (
  await Promise.all(scanRoots.map((root) => collectFiles(root)))
).flat();
const excludedRoots = [generatedRoot, tokenRoot];
const checks = [
  {
    pattern:
      /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\s*\(|\b(?:hwb|lab|lch|oklab|oklch)\s*\(/g,
    message: "raw color found outside token sources",
  },
  {
    pattern: /\bdark:/g,
    message: "dark: variant bypasses semantic appearance tokens",
  },
  {
    pattern: /!important/g,
    message: "!important is forbidden in product styling",
  },
  {
    pattern: /var\(--(?:primitive|palette)-/g,
    message:
      "primitive/palette CSS variables may not be consumed by components",
  },
  {
    pattern: /color-mix\(in_srgb/g,
    message: "use a perceptual color-mix space such as in_oklab",
  },
  {
    pattern: /text-\[(?:11|13)px\]/g,
    message: "use the text-caption or text-ui typography token",
  },
];

for (const filePath of scannedFiles) {
  if (
    excludedRoots.some(
      (root) => filePath === root || filePath.startsWith(`${root}${path.sep}`),
    ) ||
    !new Set([".ts", ".tsx", ".css"]).has(path.extname(filePath))
  ) {
    continue;
  }
  const contents = await readFile(filePath, "utf8");
  for (const { pattern, message } of checks) {
    for (const match of contents.matchAll(pattern)) {
      report(
        `${path.relative(webRoot, filePath)}:${lineNumber(contents, match.index)}: ${message}`,
      );
    }
  }
}

const preview = await readFile(
  path.join(webRoot, ".storybook", "preview.tsx"),
  "utf8",
);
for (const globalName of ["theme", "appearance", "locale", "network", "data"]) {
  if (!preview.includes(`${globalName}: {`)) {
    report(`.storybook/preview.tsx: missing ${globalName} global control`);
  }
}
if (!preview.includes('a11y: { test: "error" }')) {
  report(
    ".storybook/preview.tsx: accessibility checks must fail on violations",
  );
}

const featureRoot = path.join(sourceRoot, "features");
const featureEntries = await readdir(featureRoot, { withFileTypes: true });
for (const entry of featureEntries.filter((item) => item.isDirectory())) {
  const files = await collectFiles(path.join(featureRoot, entry.name));
  if (!files.some((file) => file.endsWith(".stories.tsx"))) {
    report(
      `src/features/${entry.name}: implemented feature has no Storybook state catalog`,
    );
  }
}

if (violations.length > 0) {
  console.error("Design-system contract violations:\n");
  console.error(violations.map((violation) => `- ${violation}`).join("\n"));
  process.exit(1);
}

const storyCount = scannedFiles.filter((file) =>
  file.endsWith(".stories.tsx"),
).length;
console.log(
  `Design-system contract is clean (${light.size} semantic tokens per appearance, ${storyCount} story files).`,
);
