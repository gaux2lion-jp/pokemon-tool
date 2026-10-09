# Product images and reviewed Discord posting

Product images live in the public `sumdex-products` Storage bucket. Catalog JSON stores `imagePath`, not image bytes. Uploads normalize to WebP at a maximum 1000px long edge, preserve aspect ratio and transparency, and never upscale. Existing posted image URLs are immutable; removing a catalog association does not break previous Discord posts.

## Setup

1. Apply `image-post-schema.sql` once to the existing project. It creates member-only uploads and service-only configuration/post snapshots. Public image reading is intentional.
2. Deploy `edge-functions/sumdex-discord-post/index.ts` with its relative dependencies. The function explicitly validates the Supabase user and active Google membership via the existing members RLS. Gateway JWT verification is disabled only because this custom authorization is implemented. Built-in Supabase URL, anon and service role environment variables are required.
3. In the app's settings, an administrator registers a separate sales-channel Discord webhook. The server validates the webhook without sending a message. Its URL is never returned to the client.
4. Add images in the product catalog, then click 商品表を共有保存.
5. Build a preview, review the destination, prices, conditions and images, check the confirmation, and click この内容でDiscordに投稿する.

## Behavior

- Each product is one large-image embed; conditions are sorted S/A, AM, B regardless of input order. Product code is optional. Images are optional and explicitly described as reference images.
- Payloads are split at eight products or a conservative 5800 embed characters. The preview shows exactly the server-stored payload and number of messages. Discord may render sizing differently by device.
- The server rechecks live Notion prices during prepare and posting. Changed product data or destination invalidates the preview. Previews expire after ten minutes.
- Server-side state changes atomically from ready to sending before contacting Discord. Concurrent clicks cannot send the same preview twice. Failed or ambiguous sends are marked uncertain and never automatically retried. Check Discord before creating another preview. Partial successful message links are retained.
- URL import currently accepts cdn.snkrdunk.com only (no redirects); upload a JPEG, PNG or WebP file for other sources. Use images you can use in your listing.
- This replaces the copy-to-clipboard posting UI. Existing scraper notification webhooks are untouched.

## Verification

`npm ci`, `npm test`, `npm run build` from discord-template. Handler tests mock external calls: they do not post to Discord. A real send still requires registering a sales webhook and user confirmation in the app.
