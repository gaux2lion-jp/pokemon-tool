import test from 'node:test';import assert from 'node:assert/strict';import {build} from 'esbuild';
// Compile the real handler; replace only the external Notion network dependency.
let handler,sentPayload,sends=0,state='ready',config={url:'https://discord.com/api/webhooks/123/token',name:'sales',channelId:'2',guildId:'1'};
const product={id:'p',ja:'商品',en:'Box',price:10000,sourceUrl:'SUMdex-Price-List',code:''};
const row={productId:'p',conditions:['sa'],cost:9000,manualPrice:9900};let post;
const bundled=await build({entryPoints:['edge-functions/sumdex-discord-post/index.ts'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'notion',setup(b){b.onLoad({filter:/sumdex-notion-prices\/notion\.js$/},()=>({contents:'export async function fetchNotionSource(){return {source:"pokemon",rows:[{name:"Box",price:10000}],url:"SUMdex-Price-List"}}'}));}}]});
globalThis.Deno={env:{get:k=>({SUPABASE_URL:'https://database.test',SUPABASE_ANON_KEY:'anon',SUPABASE_SERVICE_ROLE_KEY:'secret'}[k])},serve:fn=>handler=fn};
await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const realFetch=globalThis.fetch;
function setup({member=true,authorized=true,timeout=false}={}){sends=0;state='ready';post=null;globalThis.fetch=async(url,opts={})=>{url=String(url);const json=x=>new Response(JSON.stringify(x),{status:200});
 if(url.endsWith('/auth/v1/user'))return authorized?json({id:'11111111-1111-1111-1111-111111111111',email:'member@example.com'}):new Response('',{status:401});
 if(url.includes('sumdex_members'))return json(member?[{active:true,role:'admin'}]:[]);
 if(url.includes('sumdex_post_config'))return json([{data:config}]);
 if(url.includes('sumdex_documents'))return json([{id:'catalog',data:{products:[product]}},{id:'settings',data:{}}]);
 if(url.includes('sumdex_posts')){if(opts.method==='POST'){post={...JSON.parse(opts.body),created_at:new Date().toISOString()};return json([post]);}if(opts.method==='PATCH'){if(url.includes('state=eq.ready')&&state!=='ready')return json([]);const update=JSON.parse(opts.body);Object.assign(post,update);state=update.state||state;return json([post]);}return json([{...post,state}]);}
 if(url.includes('/storage/v1/object/public/sumdex-products/'))return new Response(null,{status:200,headers:{'content-type':'image/webp','content-length':'1024'}});
 if(url.includes('discord.com')){sentPayload=JSON.parse(opts.body);sends++;if(timeout)throw Error('timeout');return json({id:'message'});}throw Error('Unexpected URL');};}
const call=async body=>{const r=await handler(new Request('https://function.test',{method:'POST',headers:{authorization:'Bearer x'},body:JSON.stringify(body)}));return {status:r.status,...await r.json()};};
test('handler authorization, preview, send once, and ambiguous failure',async()=>{try{
 setup({authorized:false});assert.equal((await call({action:'status'})).status,401);
 setup({member:false});assert.equal((await call({action:'status'})).status,403);
 setup();const p=await call({action:'prepare',rows:[row]});assert.ok(p.id);assert.equal(sends,0);assert.equal(p.messages.length,1);
 const [a,b]=await Promise.all([call({action:'post',id:p.id}),call({action:'post',id:p.id})]);assert.equal(sends,1);assert.ok([a,b].some(x=>x.state==='sent'));
 await call({action:'post',id:p.id});assert.equal(sends,1);
 setup({timeout:true});const t=await call({action:'prepare',rows:[row]});assert.equal((await call({action:'post',id:t.id})).state,'uncertain');await call({action:'post',id:t.id});assert.equal(sends,1);
 }finally{globalThis.fetch=realFetch;}});

test('card previews send the reviewed image and edits invalidate old cards',async()=>{try{
 setup();let preview=await call({action:'prepare',rows:[row]});
 const cards=[{mi:0,ei:0,path:'11111111-1111-1111-1111-111111111111/post-cards/22222222-2222-2222-2222-222222222222.webp'}];
 assert.equal((await call({action:'cards',id:preview.id,cards:[]})).status,400);
 assert.equal((await call({action:'cards',id:preview.id,cards:[{...cards[0],path:cards[0].path.replace('11111111','33333333')}]})).status,400);
 preview=await call({action:'cards',id:preview.id,cards});assert.ok(preview.cardMessages[0].embeds[0].image);assert.equal(sends,0);
 assert.equal((await call({action:'post',id:preview.id})).state,'sent');assert.deepEqual(sentPayload,preview.cardMessages[0]);
 setup();preview=await call({action:'prepare',rows:[row]});preview=await call({action:'cards',id:preview.id,cards});
 preview.messages[0].embeds[0].title='Edited box';
 const revised=await call({action:'revise',id:preview.id,messages:preview.messages});assert.equal(revised.status,200);assert.equal(post.data.cardMessages,undefined);assert.equal(sends,0);
 const refreshed=await call({action:'cards',id:revised.id,cards});assert.equal(refreshed.messages[0].embeds[0].title,'Edited box');assert.ok(refreshed.cardMessages);assert.equal(sends,0);
 }finally{globalThis.fetch=realFetch;}});
