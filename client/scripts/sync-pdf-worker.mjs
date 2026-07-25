import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const clientDirectory = path.resolve(scriptDirectory, "..");
const packageManifest = JSON.parse(
	readFileSync(path.join(clientDirectory, "package.json"), "utf8")
);

const pdfPackagePath = require.resolve("pdfjs-dist/package.json");
const pdfPackageDirectory = path.dirname(pdfPackagePath);
const installedManifest = JSON.parse(readFileSync(pdfPackagePath, "utf8"));
const pinnedVersion = packageManifest.resolutions?.["pdfjs-dist"];

if (installedManifest.version !== pinnedVersion) {
	throw new Error(
		`pdfjs-dist worker mismatch: package.json pins ${pinnedVersion}, ` +
			`but node_modules contains ${installedManifest.version}`
	);
}

const source = path.join(pdfPackageDirectory, "build", "pdf.worker.mjs");
const destinationDirectory = path.join(clientDirectory, "public");
const destination = path.join(destinationDirectory, "pdf.worker.mjs");

mkdirSync(destinationDirectory, { recursive: true });
copyFileSync(source, destination);
console.log(`Synced PDF.js worker ${installedManifest.version}`);
