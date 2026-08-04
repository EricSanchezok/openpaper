import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const webRoot = path.resolve(import.meta.dirname, "..");
const sourceRoot = path.join(webRoot, "src");
const generatedDirectories = [
  path.join(sourceRoot, "design-system", "generated"),
  path.join(sourceRoot, "lib", "api", "generated"),
];
const sourceExtensions = new Set([".ts", ".tsx", ".css"]);
const importPattern =
  /(?:from\s+|import\s*\(|require\s*\()\s*["']([^"']+)["']/g;
const rawColorPattern = /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\s*\(/;
const forbiddenIconPackages = [
  "lucide",
  "@heroicons",
  "react-icons",
  "phosphor",
  "@tabler/icons",
];

function isInside(filePath, directory) {
  return (
    filePath === directory || filePath.startsWith(`${directory}${path.sep}`)
  );
}

async function collectFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (
      generatedDirectories.some((generated) => isInside(entryPath, generated))
    ) {
      continue;
    }
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(entryPath)));
    } else if (sourceExtensions.has(path.extname(entry.name))) {
      files.push(entryPath);
    }
  }
  return files;
}

function relative(filePath) {
  return path.relative(webRoot, filePath);
}

function report(violations, filePath, message) {
  violations.push(`${relative(filePath)}: ${message}`);
}

function featureName(filePath) {
  const relativePath = path.relative(
    path.join(sourceRoot, "features"),
    filePath,
  );
  if (relativePath.startsWith("..")) return undefined;
  return relativePath.split(path.sep)[0];
}

function importedFeature(specifier) {
  const match = specifier.match(/^@\/features\/([^/]+)(?:\/(.*))?$/);
  return match ? { name: match[1], privatePath: match[2] } : undefined;
}

const files = await collectFiles(sourceRoot);
const violations = [];

for (const filePath of files) {
  const contents = await readFile(filePath, "utf8");
  const ownFeature = featureName(filePath);

  if (rawColorPattern.test(contents)) {
    report(
      violations,
      filePath,
      "raw color found outside token sources/generated output; use a semantic token",
    );
  }
  if (/<svg\b|createElement\(\s*["']svg["']/.test(contents)) {
    report(
      violations,
      filePath,
      "manually rendered SVG found; add an Iconoir glyph through the Scholens Icon wrapper",
    );
  }

  for (const match of contents.matchAll(importPattern)) {
    const specifier = match[1];
    if (!specifier) continue;

    if (
      specifier.includes("client/") ||
      specifier.startsWith("@client") ||
      /(?:^|\/)\.\.\/(?:\.\.\/)*client(?:\/|$)/.test(specifier)
    ) {
      report(
        violations,
        filePath,
        `legacy client import is forbidden: ${specifier}`,
      );
    }
    if (forbiddenIconPackages.some((name) => specifier.startsWith(name))) {
      report(
        violations,
        filePath,
        `second icon system is forbidden: ${specifier}`,
      );
    }

    if (!specifier.startsWith("@/")) continue;

    if (isInside(filePath, path.join(sourceRoot, "design-system"))) {
      if (!specifier.startsWith("@/design-system/")) {
        report(
          violations,
          filePath,
          `design-system may not depend on another source layer: ${specifier}`,
        );
      }
    }

    if (isInside(filePath, path.join(sourceRoot, "lib"))) {
      if (/^@\/(?:app|components|features)\//.test(specifier)) {
        report(
          violations,
          filePath,
          `lib may not depend on product/UI code: ${specifier}`,
        );
      }
    }

    if (isInside(filePath, path.join(sourceRoot, "components", "ui"))) {
      if (
        /^@\/(?:app|features)\//.test(specifier) ||
        /^@\/lib\/(?:api|query)\//.test(specifier)
      ) {
        report(
          violations,
          filePath,
          `UI primitive has a forbidden dependency: ${specifier}`,
        );
      }
    }

    if (isInside(filePath, path.join(sourceRoot, "components", "feedback"))) {
      if (
        /^@\/(?:app|features)\//.test(specifier) ||
        /^@\/lib\/(?:api|query)\//.test(specifier)
      ) {
        report(
          violations,
          filePath,
          `feedback primitive has a forbidden dependency: ${specifier}`,
        );
      }
    }

    const targetFeature = importedFeature(specifier);
    if (targetFeature?.privatePath && targetFeature.name !== ownFeature) {
      report(
        violations,
        filePath,
        `feature private import is forbidden; import @/features/${targetFeature.name}: ${specifier}`,
      );
    }
  }
}

if (violations.length > 0) {
  console.error("Architecture contract violations:\n");
  console.error(violations.map((violation) => `- ${violation}`).join("\n"));
  process.exit(1);
}

console.log(
  `Architecture contract is clean (${files.length} source files checked).`,
);
