import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const clientRoot = resolve(repositoryRoot, "dist", "client");
const workerPath = resolve(repositoryRoot, "dist", "server", "index.js");
const { default: worker } = await import(pathToFileURL(workerPath));

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json"],
  [".svg", "image/svg+xml"],
]);

function assetsBinding() {
  return {
    async fetch(request) {
      const pathname = decodeURIComponent(new URL(request.url).pathname);
      const relativePath = pathname.replace(/^\/+/, "");
      const filePath = resolve(clientRoot, relativePath);
      const pathFromClientRoot = relative(clientRoot, filePath);

      if (pathFromClientRoot.startsWith("..") || isAbsolute(pathFromClientRoot)) {
        return new Response("Not found", { status: 404 });
      }

      try {
        const body = await readFile(filePath);
        const extension = filePath.slice(filePath.lastIndexOf("."));
        return new Response(request.method === "HEAD" ? null : body, {
          headers: { "Content-Type": contentTypes.get(extension) ?? "application/octet-stream" },
        });
      } catch {
        return new Response("Not found", { status: 404 });
      }
    },
  };
}

async function request(path, init) {
  return worker.fetch(
    new Request(`https://handbook.example${path}`, init),
    { ASSETS: assetsBinding() },
  );
}

test("serves the generated homepage with security headers", async () => {
  const response = await request("/");
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html/);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.match(await response.text(), /FastAPI Backend Engineering/i);
});

test("redirects directory paths to their canonical trailing slash", async () => {
  const response = await request("/docs/00-foundations/python-for-backend");
  assert.equal(response.status, 308);
  assert.equal(
    response.headers.get("location"),
    "https://handbook.example/docs/00-foundations/python-for-backend/",
  );
});

test("serves a branded 404 page with a 404 status", async () => {
  const response = await request("/definitely-missing-page/");
  assert.equal(response.status, 404);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html/);
});

test("rejects unsupported methods", async () => {
  const response = await request("/", { method: "POST" });
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD");
});
