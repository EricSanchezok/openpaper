import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const task = process.argv[2];

if (!new Set(["tokens", "api"]).has(task)) {
  throw new Error("Usage: node scripts/check-generated.mjs <tokens|api>");
}

const generatedPath =
  task === "tokens"
    ? path.join(root, "src/design-system/generated")
    : path.join(root, "src/lib/api/generated/schema.d.ts");
const temporaryDirectory = fs.mkdtempSync(
  path.join(os.tmpdir(), `scholens-${task}-`),
);
const regeneratedPath =
  task === "tokens"
    ? path.join(temporaryDirectory, "generated")
    : path.join(temporaryDirectory, "schema.d.ts");

if (task === "tokens") {
  execFileSync("node", ["scripts/build-tokens.mjs"], {
    cwd: root,
    env: { ...process.env, SCHOLENS_TOKEN_OUTPUT_DIR: regeneratedPath },
    stdio: "inherit",
  });
} else {
  execFileSync(
    "pnpm",
    [
      "exec",
      "openapi-typescript",
      "../server/openapi/public-v1.json",
      "-o",
      regeneratedPath,
    ],
    { cwd: root, stdio: "inherit" },
  );
}

const compare = (left, right) => {
  const leftStat = fs.statSync(left);
  const rightStat = fs.statSync(right);
  if (leftStat.isDirectory() !== rightStat.isDirectory()) return false;
  if (!leftStat.isDirectory())
    return fs.readFileSync(left).equals(fs.readFileSync(right));
  const leftEntries = fs.readdirSync(left).sort();
  const rightEntries = fs.readdirSync(right).sort();
  return (
    leftEntries.length === rightEntries.length &&
    leftEntries.every(
      (entry, index) =>
        entry === rightEntries[index] &&
        compare(path.join(left, entry), path.join(right, entry)),
    )
  );
};

if (!compare(generatedPath, regeneratedPath)) {
  throw new Error(
    task === "tokens"
      ? "Token outputs are stale. Run pnpm tokens:build."
      : "API types are stale. Run pnpm api:generate.",
  );
}
