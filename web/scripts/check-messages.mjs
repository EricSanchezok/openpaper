import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const messagesDirectory = path.join(root, "src", "i18n", "messages");
const locales = ["en", "zh-CN", "zh-TW"];

function flatten(value, prefix = "", result = new Map()) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${prefix || "<root>"} must be an object`);
  }

  for (const [key, child] of Object.entries(value)) {
    const current = prefix ? `${prefix}.${key}` : key;
    if (typeof child === "string") {
      result.set(current, child);
    } else {
      flatten(child, current, result);
    }
  }

  return result;
}

function argumentsFor(message) {
  return [...message.matchAll(/\{\s*([A-Za-z][\w]*)\s*(?=,|\})/g)]
    .map((match) => match[1])
    .sort()
    .join(",");
}

const dictionaries = new Map();
for (const locale of locales) {
  const source = await readFile(
    path.join(messagesDirectory, `${locale}.json`),
    "utf8",
  );
  dictionaries.set(locale, flatten(JSON.parse(source)));
}

const canonical = dictionaries.get("en");
const errors = [];
for (const locale of locales.slice(1)) {
  const candidate = dictionaries.get(locale);
  for (const [key, message] of canonical) {
    if (!candidate.has(key)) {
      errors.push(`${locale}: missing ${key}`);
      continue;
    }
    const canonicalArguments = argumentsFor(message);
    const candidateArguments = argumentsFor(candidate.get(key));
    if (canonicalArguments !== candidateArguments) {
      errors.push(
        `${locale}: ${key} uses arguments [${candidateArguments}] instead of [${canonicalArguments}]`,
      );
    }
  }
  for (const key of candidate.keys()) {
    if (!canonical.has(key)) errors.push(`${locale}: unexpected ${key}`);
  }
}

if (errors.length > 0) {
  console.error(`Message catalog check failed:\n${errors.join("\n")}`);
  process.exit(1);
}

console.log(
  `Message catalogs are aligned (${canonical.size} messages, ${locales.length} locales).`,
);
