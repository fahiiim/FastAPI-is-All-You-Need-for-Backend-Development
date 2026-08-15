import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const stageRoot = resolve(repositoryRoot, ".mkdocs-source");
const documentationDirectories = [
  "architecture",
  "decision-guides",
  "docs",
  "examples",
  "interview",
  "resources",
];
const rootFiles = [
  "README.md",
  "CONTRIBUTING.md",
  "SECURITY.md",
  "LICENSE",
  "backend-project-structure.md",
];

async function copyMarkdownTree(sourceRoot, targetRoot) {
  const entries = await readdir(sourceRoot, { withFileTypes: true });
  for (const entry of entries) {
    const source = resolve(sourceRoot, entry.name);
    const target = resolve(targetRoot, entry.name);

    if (entry.isDirectory()) {
      await copyMarkdownTree(source, target);
      continue;
    }

    if (entry.isFile() && extname(entry.name).toLowerCase() === ".md") {
      await mkdir(targetRoot, { recursive: true });
      await cp(source, target);
    }
  }
}

await rm(stageRoot, { recursive: true, force: true });
await mkdir(stageRoot, { recursive: true });

for (const file of rootFiles) {
  await cp(resolve(repositoryRoot, file), resolve(stageRoot, file));
}

for (const directory of documentationDirectories) {
  await copyMarkdownTree(
    resolve(repositoryRoot, directory),
    resolve(stageRoot, directory),
  );
}

console.log("Staged authored Markdown for MkDocs.");
