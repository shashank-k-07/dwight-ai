// The dashboard calls relative /api/* URLs; Next proxies them to the Dwight API.
// DWIGHT_API_URL is the API base URL (default http://localhost:8000). Set it when
// running `next dev` / `next build`.
const API = process.env.DWIGHT_API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
export default nextConfig;
