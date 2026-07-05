/**
 * PRIMUS — Frontend Configuration
 *
 * Single source of truth for all frontend ↔ backend communication.
 * Change BACKEND_URL and LEDGER_URL here; nowhere else.
 *
 * DEPLOY CHECKLIST
 * ────────────────
 *  1. Replace BACKEND_URL with your Render service URL.
 *  2. Replace LEDGER_URL with the Vercel URL of the Ledger deployment.
 *  3. Commit. Push. Drop-to-Deploy on Vercel.
 *  4. Done — every page picks these up automatically.
 */
var CONFIG = {
  /**
   * The public HTTPS URL of the Render-hosted backend.
   * No trailing slash.
   *
   * Example: "https://primus-backend.onrender.com"
   */
  BACKEND_URL: "https://primus-lyq1.onrender.com",

  /**
   * The public URL of the deployed Ledger frontend.
   * The Wizard redirects here after a successful launch.
   *
   * Separate from the Wizard deployment so each frontend can be
   * deployed independently on Vercel.
   *
   * For local development this falls back to the relative path
   * ../ledger/index.html (resolved at runtime — see Wizard code).
   *
   * Example: "https://primus-ledger.vercel.app"
   */
  LEDGER_URL: "https://primus-ledger.vercel.app"
};

// Safety-net: catch accidental relative-URL usage in other scripts.
if (typeof window !== "undefined") {
  window.PRIMUS_CONFIG = CONFIG;
}
