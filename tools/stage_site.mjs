import { access, cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const sourceDirectory = resolve(repositoryRoot, ".site-build");
const publicDirectory = resolve(repositoryRoot, "hosting", "public");

try {
  await access(resolve(sourceDirectory, "index.html"));
} catch {
  throw new Error("MkDocs output is missing. Run the strict documentation build first.");
}

await rm(publicDirectory, { recursive: true, force: true });
await mkdir(publicDirectory, { recursive: true });
await cp(sourceDirectory, publicDirectory, { recursive: true });

console.log("Staged the MkDocs output for the hosting adapter.");
