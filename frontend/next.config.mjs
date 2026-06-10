/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * API proxy rewrites.
   *
   * Browser requests to /api/* are rewritten to the Railway backend.
   * Server Components use process.env.API_URL directly (see lib/api.ts)
   * because relative URLs are invalid in Node.js fetch.
   *
   * Set API_URL in:
   *   local dev:  .env.local  →  API_URL=http://localhost:8000
   *   Vercel:     dashboard   →  API_URL=https://equity-research-api-production.up.railway.app
   */
  async rewrites() {
    const dest = process.env.API_URL ?? "http://localhost:8000"
    return [
      {
        source: "/api/:path*",
        destination: `${dest}/api/:path*`,
      },
    ]
  },
}

export default nextConfig;
