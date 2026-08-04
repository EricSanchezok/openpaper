import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const repositoryRoot = path.resolve(import.meta.dirname, "..", "..");
const webRoot = path.join(repositoryRoot, "web");
const documentationRoots = [
  path.join(repositoryRoot, "AGENTS.md"),
  path.join(repositoryRoot, "DEVELOPMENT.md"),
  path.join(repositoryRoot, "PRODUCT.md"),
  path.join(webRoot, "README.md"),
  path.join(webRoot, "docs"),
];
const markdownLinkPattern = /!?(?:\[[^\]]*\])\(([^)]+)\)/g;

async function collectMarkdown(target) {
  const entries = await readdir(target, { withFileTypes: true }).catch(
    () => undefined,
  );
  if (!entries) return [target];
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(target, entry.name);
    if (entry.isDirectory()) files.push(...(await collectMarkdown(entryPath)));
    else if (entry.name.endsWith(".md")) files.push(entryPath);
  }
  return files;
}

function display(filePath) {
  return path.relative(repositoryRoot, filePath);
}

const files = (
  await Promise.all(documentationRoots.map((target) => collectMarkdown(target)))
).flat();
const violations = [];

for (const filePath of files) {
  const contents = await readFile(filePath, "utf8");
  for (const match of contents.matchAll(markdownLinkPattern)) {
    const rawTarget = match[1]?.trim();
    if (
      !rawTarget ||
      rawTarget.startsWith("#") ||
      /^[a-z][a-z0-9+.-]*:/i.test(rawTarget)
    ) {
      continue;
    }
    const withoutTitle = rawTarget.match(
      /^<?([^ >]+)>?(?:\s+["'][^"']*["'])?$/,
    )?.[1];
    if (!withoutTitle) continue;
    const decodedTarget = decodeURIComponent(withoutTitle.split("#")[0] ?? "");
    if (!decodedTarget) continue;
    const resolved = path.resolve(path.dirname(filePath), decodedTarget);
    try {
      await access(resolved);
    } catch {
      violations.push(`${display(filePath)}: broken local link ${rawTarget}`);
    }
  }
}

const packageJson = JSON.parse(
  await readFile(path.join(webRoot, "package.json"), "utf8"),
);
const expectedScripts = {
  dev: "next dev --hostname 127.0.0.1 --port 7300",
  start: "next start --hostname 127.0.0.1 --port 7300",
  storybook: "storybook dev -p 7306 --host 127.0.0.1 --exact-port --no-open",
};
for (const [name, expected] of Object.entries(expectedScripts)) {
  if (packageJson.scripts?.[name] !== expected) {
    violations.push(
      `web/package.json: ${name} must remain ${JSON.stringify(expected)}`,
    );
  }
}

const activePortDocs = [
  path.join(repositoryRoot, "AGENTS.md"),
  path.join(repositoryRoot, "DEVELOPMENT.md"),
  path.join(webRoot, "README.md"),
];
for (const filePath of activePortDocs) {
  const contents = await readFile(filePath, "utf8");
  if (/localhost:300[0136]|127\.0\.0\.1:300[0136]/.test(contents)) {
    violations.push(
      `${display(filePath)}: stale pre-contract frontend port found`,
    );
  }
}

const decisionsDirectory = path.join(webRoot, "docs", "decisions");
const decisionFiles = (await readdir(decisionsDirectory))
  .filter((name) => /^\d{4}-.+\.md$/.test(name))
  .sort();
const decisionIndex = await readFile(
  path.join(decisionsDirectory, "README.md"),
  "utf8",
);
for (const decisionFile of decisionFiles) {
  if (!decisionIndex.includes(`./${decisionFile}`)) {
    violations.push(`web/docs/decisions/README.md: missing ${decisionFile}`);
  }
}

if (violations.length > 0) {
  console.error("Documentation contract violations:\n");
  console.error(violations.map((violation) => `- ${violation}`).join("\n"));
  process.exit(1);
}

console.log(
  `Documentation contract is clean (${files.length} Markdown files checked).`,
);
