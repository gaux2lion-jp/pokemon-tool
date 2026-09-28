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

## Price list operation

Generation and copying now fetch both public Notion price lists on demand through the authenticated `sumdex-notion-prices` Edge Function. The function reads public page/collection data, requires a valid user session plus an active member, and returns a complete name/price list; incomplete data and unexpected schema fail closed. The operator may bind a verified Notion row to a catalog product; otherwise an exact English or Japanese name (including a code suffix) or an unambiguous code match is used. Shipping variants and duplicate code matches require manual selection. Changes in the live price update the shared catalog before generating the text; changes detected when copying cancel the copy and require regeneration. Existing Discord posts cannot be changed automatically.

Use the catalog CSV to bulk register Japanese scraper names (`ja`), English names (`en`), set codes (`code`), and additional exact Japanese variants (`domesticNames`, separated by `|`). The operator verifies uncertain name matches. Duplicate Japanese aliases across products are rejected on shared save. The buyer post uses the English name, while the same catalog product resolves domestic quotes by the verified Japanese aliases. Operators can search the purchase entry by either language or code.
The "国内未登録名のCSVひな形" button exports names from the scraper that have no mapping yet. Fill an English posting name or set code for each product to map; untouched template rows are skipped. Mapping only rows can be imported and shared before SUMdex prices are known. Set codes compare without regard to case and may occur on multiple different products. Operators may use English names verified on other sites, and add Japanese variants in `domesticNames` (separated by `|`). The editable catalog has search, add, remove, and explicit shared save. The save status displays the number of products. To make a product saleable, add the visual SUMdex price and source URL, click the confirmation button, and save again. A changed price or source URL clears a previous confirmation. Sale generation continues to block products without English name, set code, current verified price and nonnegative profit.

For price lists, select the Pokémon or ONE PIECE source and click "Notion価格を今確認"; review the English name/code matches and manually resolve ambiguous rows. Apply and save the shared catalog to pin the chosen Notion row IDs. An exported CSV remains an operator fallback if Notion's undocumented public collection endpoint changes. It accepts a product name or code column and a price column, and blocks malformed or conflicting prices. A supported long-term integration would need server-side Notion authorization granted by the owner of both price pages.

The domestic parser uses the existing generated `docs/index.html` without modifying the original scraper. Display prices and guarantee text are preserved; damage deductions are never invented.

Documents use optimistic concurrency: updates include the prior version, and a database trigger requires exactly one version increment. Conflicts do not overwrite other users' changes. Membership is checked live against verified Google-linked users, not user-editable metadata. Public frontend contains no membership email allowlist and no private purchase data.

Refund is a user-selected estimate (`purchase / 11`), not a tax eligibility determination. Zero profit is allowed; negative profit and sale above the SUMdex reference price block generation until adjusted or excluded.
