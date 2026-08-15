import handler from "vinext/server/app-router-entry";

interface Env {
  ASSETS?: Fetcher;
}

interface WorkerContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

const FILE_EXTENSION = /\.[a-z0-9]+$/i;

function assetRequest(request: Request, pathname: string): Request {
  const url = new URL(request.url);
  url.pathname = pathname;
  return new Request(url, {
    method: request.method,
    headers: request.headers,
  });
}

function addSecurityHeaders(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function serveNotFound(request: Request, assets: Fetcher): Promise<Response> {
  const response = await assets.fetch(assetRequest(request, "/404.html"));
  if (!response.ok) {
    return new Response("Not found", { status: 404 });
  }

  return new Response(response.body, {
    status: 404,
    headers: response.headers,
  });
}

const worker = {
  async fetch(request: Request, env: Env, context: WorkerContext): Promise<Response> {
    if (!env.ASSETS) {
      return handler.fetch(request, env, context);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return addSecurityHeaders(
        new Response("Method not allowed", {
          status: 405,
          headers: { Allow: "GET, HEAD" },
        }),
      );
    }

    const url = new URL(request.url);
    const pathname = url.pathname;

    if (pathname.endsWith("/")) {
      const response = await env.ASSETS.fetch(
        assetRequest(request, `${pathname}index.html`),
      );
      if (response.ok) {
        return addSecurityHeaders(response);
      }
      return addSecurityHeaders(await serveNotFound(request, env.ASSETS));
    }

    const exactResponse = await env.ASSETS.fetch(request);
    if (exactResponse.ok) {
      return addSecurityHeaders(exactResponse);
    }

    if (!FILE_EXTENSION.test(pathname)) {
      const indexResponse = await env.ASSETS.fetch(
        assetRequest(request, `${pathname}/index.html`),
      );
      if (indexResponse.ok) {
        const redirect = new URL(request.url);
        redirect.pathname = `${pathname}/`;
        return addSecurityHeaders(Response.redirect(redirect, 308));
      }
    }

    return addSecurityHeaders(await serveNotFound(request, env.ASSETS));
  },
};

export default worker;
