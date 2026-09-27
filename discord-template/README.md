# SUMdex Discord Studio

Template-specific sources are isolated here. Static output is in `docs/discord-template`.

## Build

`npm ci && npm test && npm run build` in this directory.

## Deployment prerequisites

1. Apply `schema.sql` once on the selected Supabase project. It enables RLS and denies unauthenticated access.
2. Privately seed `sumdex_members` with the approved administrator and editors. Do not commit real membership emails or purchase data.
3. Configure Google OAuth and the exact application redirect URL in Supabase Auth URL Configuration.
4. Put only the publishable key in `src/config.js`, then rebuild.
5. Verify allowed and denied authenticated access, concurrent document saves, and Google login before release.

## Current limitation — not production complete

Public Notion automatic ingestion is not connected. The public data endpoint returned HTTP 403 during implementation. The UI explicitly labels manual prices, requires source URL and a recent confirmation timestamp, and validates against the shared catalog at generation/copy. It does not claim validation against the live Notion original. This does **not** fulfill the final automatic Notion synchronization requirement. Connect an authorized Notion integration or a supported export source before calling the project complete.

The domestic parser uses the existing generated `docs/index.html` without modifying the original scraper. Display prices and guarantee text are preserved; damage deductions are never invented.

Documents use optimistic concurrency: updates include the prior version, and a database trigger requires exactly one version increment. Conflicts do not overwrite other users' changes. Membership is checked live against verified Google-linked users, not user-editable metadata. Public frontend contains no membership email allowlist and no private purchase data.

Refund is a user-selected estimate (`purchase / 11`), not a tax eligibility determination. Zero profit is allowed; negative profit and sale above the SUMdex reference price block generation until adjusted or excluded.
