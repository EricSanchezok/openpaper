import { cpSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const clientDirectory = path.resolve(scriptDirectory, "..");
const standaloneDirectory = path.join(clientDirectory, ".next", "standalone");
const serverPath = path.join(standaloneDirectory, "server.js");

if (!existsSync(serverPath)) {
	throw new Error("Standalone build not found. Run `yarn build` first.");
}

const standaloneNextDirectory = path.join(standaloneDirectory, ".next");
mkdirSync(standaloneNextDirectory, { recursive: true });
cpSync(
	path.join(clientDirectory, ".next", "static"),
	path.join(standaloneNextDirectory, "static"),
	{ recursive: true, force: true },
);
cpSync(
	path.join(clientDirectory, "public"),
	path.join(standaloneDirectory, "public"),
	{ recursive: true, force: true },
);

await import(pathToFileURL(serverPath).href);
