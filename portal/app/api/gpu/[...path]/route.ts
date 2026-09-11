import type { NextRequest } from "next/server";

/**
 * Same-origin reverse proxy to the internal GPU FastAPI server.
 *
 * The browser only ever talks to the homepage origin (`/api/gpu/*`). This
 * handler runs on the NAS Node server (LAN) and forwards each request to
 * `GPU_API_URL` over the internal network, so the GPU box is never exposed to
 * the browser or the public internet.
 *
 * `GPU_API_URL` is server-only (NOT `NEXT_PUBLIC_`) — set it to the GPU
 * server's LAN address (e.g. http://10.0.0.5:8000) reachable from this
 * container. See `portal/.env.local.example`.
 *
 * Handles JSON, SSE (text/event-stream), images (PNG) and ZIP downloads
 * uniformly by streaming the upstream body straight through.
 *
 * SECURITY: this proxy relays the *entire* GPU API. The homepage's auth
 * middleware MUST gate `/api/gpu/*` (Next.js matchers often exclude `/api`),
 * otherwise this becomes an open relay.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const GPU_API_URL = process.env.GPU_API_URL ?? "http://localhost:8000";

// Hop-by-hop / length headers that must NOT be copied onto a streamed proxy
// response — keeping them causes SSE to hang and ZIP/PNG bodies to truncate.
const STRIPPED_RESPONSE_HEADERS = new Set([
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "connection",
  "keep-alive",
]);

async function proxy(
  request: NextRequest,
  pathSegments: string[],
): Promise<Response> {
  const path = pathSegments.join("/");
  const target = `${GPU_API_URL}/${path}${request.nextUrl.search}`;

  // Forward only what the upstream needs; let fetch set Host / Content-Length.
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType); // preserves multipart boundary
  const accept = request.headers.get("accept");
  if (accept) headers.set("accept", accept); // SSE sends text/event-stream
  const auth = request.headers.get("authorization");
  if (auth) headers.set("authorization", auth);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
    });

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });
    if (responseHeaders.get("content-type")?.includes("text/event-stream")) {
      responseHeaders.set("cache-control", "no-cache, no-transform");
    }

    // Stream the body through — never await/buffer it (keeps SSE incremental).
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(`[gpu-proxy] ${request.method} ${target} failed:`, error);
    return new Response(
      JSON.stringify({ detail: "Upstream GPU API unreachable" }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
}

// Next.js 15 passes route params as a Promise; `await` is also a no-op for the
// plain-object form, so this stays compatible with 14.
type RouteContext = { params: Promise<{ path?: string[] }> };

async function handle(
  request: NextRequest,
  ctx: RouteContext,
): Promise<Response> {
  const { path } = await ctx.params;
  return proxy(request, path ?? []);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const HEAD = handle;
