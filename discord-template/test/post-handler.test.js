import test from 'node:test';import assert from 'node:assert/strict';import {build} from 'esbuild';
// Compile the real handler; replace only the external Notion network dependency.
let handler,sends=0,state='ready',config={url:'https://discord.com/api/webhooks/123/token',name:'sales',channelId:'2',guildId:'1'};
const product={id:'p',ja:'商品',en:'Box',price:10000,sourceUrl:'SUMdex-Price-List',code:''};
const row={productId:'p',conditions:['sa'],cost:9000,manualPrice:9900};let post;
const bundled=await build({entryPoints:['edge-functions/sumdex-discord-post/index.ts'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'notion',setup(b){b.onLoad({filter:/sumdex-notion-prices\/notion\.js$/},()=>({contents:'export async function fetchNotionSource(){return {source:"pokemon",rows:[{name:"Box",price:10000}],url:"SUMdex-Price-List"}}'}));}}]});
globalThis.Deno={env:{get:k=>({SUPABASE_URL:'https://database.test',SUPABASE_ANON_KEY:'anon',SUPABASE_SERVICE_ROLE_KEY:'secret'}[k])},serve:fn=>handler=fn};
await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const realFetch=globalThis.fetch;
function setup({member=true,authorized=true,timeout=false}={}){sends=0;state='ready';post=null;globalThis.fetch=async(url,opts={})=>{url=String(url);const json=x=>new Response(JSON.stringify(x),{status:200});
 if(url.endsWith('/auth/v1/user'))return authorized?json({id:'user',email:'member@example.com'}):new Response('',{status:401});
 if(url.includes('sumdex_members'))return json(member?[{active:true,role:'admin'}]:[]);
 if(url.includes('sumdex_post_config'))return json([{data:config}]);
 if(url.includes('sumdex_documents'))return json([{id:'catalog',data:{products:[product]}},{id:'settings',data:{}}]);
 if(url.includes('sumdex_posts')){if(opts.method==='POST'){post=JSON.parse(opts.body);return json([post]);}if(opts.method==='PATCH'){if(url.includes('state=eq.ready')&&state!=='ready')return json([]);const update=JSON.parse(opts.body);Object.assign(post,update);state=update.state||state;return json([post]);}return json([{...post,state}]);}
 if(url.includes('discord.com')){sends++;if(timeout)throw Error('timeout');return json({id:'message'});}throw Error('Unexpected URL');};}
const call=async body=>{const r=await handler(new Request('https://function.test',{method:'POST',headers:{authorization:'Bearer x'},body:JSON.stringify(body)}));return {status:r.status,...await r.json()};};
test('handler authorization, preview, send once, and ambiguous failure',async()=>{try{
 setup({authorized:false});assert.equal((await call({action:'status'})).status,401);
 setup({member:false});assert.equal((await call({action:'status'})).status,403);
 setup();const p=await call({action:'prepare',rows:[row]});assert.ok(p.id);assert.equal(sends,0);assert.equal(p.messages.length,1);
 const [a,b]=await Promise.all([call({action:'post',id:p.id}),call({action:'post',id:p.id})]);assert.equal(sends,1);assert.ok([a,b].some(x=>x.state==='sent'));
 await call({action:'post',id:p.id});assert.equal(sends,1);
 setup({timeout:true});const t=await call({action:'prepare',rows:[row]});assert.equal((await call({action:'post',id:t.id})).state,'uncertain');await call({action:'post',id:t.id});assert.equal(sends,1);
 }finally{globalThis.fetch=realFetch;}});
