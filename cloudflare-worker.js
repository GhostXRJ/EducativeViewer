// =======Config START=======
const config = {
  // The Vercel deployment URL (handles all app pages and API routes)
  vercelBase: "https://educative-viewer.vercel.app",

  // Base URL of the static file server that serves /api/* assets
  // e.g. "https://your-r2-bucket.example.com" or "https://cdn.example.com"
  staticBase: "https://your-static-file-server.example.com",

  // URL path prefix that should be routed to the static file server
  // Requests whose pathname starts with this prefix go to staticBase;
  // everything else is proxied to vercelBase.
  staticPrefix: "/api",

  // Secret injected as the x-edu-proxy header so Vercel can verify
  // the request came through this worker
  proxySecret: "change-me",

  // Basic auth credentials to protect this worker.
  // Set both to empty strings to disable basic auth entirely.
  siteName: "EducativeViewer",
  user: "admin",
  pass: "admin",

  // Paths that bypass basic auth (exact prefix match)
  publicPaths: ["/webhook"],
};
// =======Config END=======

// ---------------------------------------------------------------------------
// Basic auth
// ---------------------------------------------------------------------------

function basicAuthResponse() {
  return new Response("Unauthorized", {
    status: 401,
    headers: {
      "WWW-Authenticate": `Basic realm="${config.siteName}"`,
      "Content-Type": "text/plain",
    },
  });
}

function checkBasicAuth(request) {
  const { user, pass } = config;
  if (!user && !pass) return true; // auth disabled if both empty
  const authHeader = request.headers.get("Authorization") || "";
  if (!authHeader.startsWith("Basic ")) return false;
  try {
    const decoded = atob(authHeader.slice(6));
    const colon = decoded.indexOf(":");
    if (colon === -1) return false;
    const u = decoded.slice(0, colon);
    const p = decoded.slice(colon + 1);
    return u === user && p === pass;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Request handler
// ---------------------------------------------------------------------------

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  const url = new URL(request.url);

  // Handle CORS preflight
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "86400",
      },
    });
  }

  // Basic auth — skip for configured public paths
  const isPublic = config.publicPaths.some((p) => url.pathname === p || url.pathname.startsWith(p + "/"));
  if (!isPublic && !checkBasicAuth(request)) {
    return basicAuthResponse();
  }

  let upstream;
  if (url.pathname.startsWith(config.staticPrefix)) {
    // Route to the static file server
    upstream = config.staticBase + url.pathname + url.search;
  } else {
    // Route to Vercel, injecting the proxy secret so Vercel can trust the request
    upstream = config.vercelBase + url.pathname + url.search;
  }

  const headers = new Headers(request.headers);
  headers.set("x-edu-proxy", config.proxySecret);
  // Remove the Host header so the upstream sees its own host
  headers.delete("host");

  try {
    const upstreamResp = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });

    const response = new Response(upstreamResp.body, {
      status: upstreamResp.status,
      headers: upstreamResp.headers,
    });

    // Inject CORS headers
    const corsHeaders = new Headers(response.headers);
    corsHeaders.set("Access-Control-Allow-Origin", "*");
    corsHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS");
    return new Response(response.body, {
      status: response.status,
      headers: corsHeaders,
    });
  } catch (err) {
    return new Response("Proxy error: " + err.message, {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    });
  }
}
