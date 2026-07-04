/**
 * PRIMUS — Frontend Configuration
 *
 * Single source of truth for all frontend ↔ backend communication.
 * Change BACKEND_URL here; nowhere else.
 *
 * DEPLOY CHECKLIST
 * ────────────────
 *  1. Replace the placeholder below with your actual Render URL.
 *  2. Commit. Push. Drop-to-Deploy on Vercel.
 *  3. Done — every page picks this up automatically.
 */
var CONFIG = {
  /**
   * The public HTTPS URL of the Render-hosted backend.
   * No trailing slash.
   *
   * Example: "https://primus-backend.onrender.com"
   */
  BACKEND_URL: "https://primus-backend.onrender.com"
};

// Safety-net: catch accidental relative-URL usage in other scripts.
if (typeof window !== "undefined") {
  window.PRIMUS_CONFIG = CONFIG;
}
