import { access, cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const sourceDirectory = resolve(repositoryRoot, "hosting", "dist");
const outputDirectory = resolve(repositoryRoot, "dist");

async function requireFile(path, message) {
  try {
    await access(path);
  } catch {
    throw new Error(message);
  }
}

await requireFile(
  resolve(sourceDirectory, "server", "index.js"),
  "The Vinext hosting adapter did not emit dist/server/index.js.",
);
await requireFile(
  resolve(repositoryRoot, ".openai", "hosting.json"),
  "Sites configuration is missing at .openai/hosting.json.",
);

await rm(outputDirectory, { recursive: true, force: true });
await cp(sourceDirectory, outputDirectory, { recursive: true });
await mkdir(resolve(outputDirectory, ".openai"), { recursive: true });
await cp(
  resolve(repositoryRoot, ".openai", "hosting.json"),
  resolve(outputDirectory, ".openai", "hosting.json"),
);

console.log("Prepared the validated Vinext bundle for Sites.");
