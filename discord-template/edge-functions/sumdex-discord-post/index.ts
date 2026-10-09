import {buildMessages} from '../../src/posting.js';
import {fetchNotionSource} from '../sumdex-notion-prices/notion.js';
import {matchLiveProduct,sourceKey} from '../../src/live-price.js';
const headers={'content-type':'application/json','access-control-allow-origin':'https://gaux2lion-jp.github.io','access-control-allow-headers':'authorization,apikey,content-type,x-client-info','access-control-allow-methods':'POST,OPTIONS','cache-control':'no-store'};
const reply=(status:number,data:unknown)=>new Response(JSON.stringify(data),{status,headers});
Deno.serve(async(req:Request)=>{
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers});
 if(req.method!=='POST')return reply(405,{error:'POSTのみ対応'});
 try{
  const base=Deno.env.get('SUPABASE_URL')!,anon=Deno.env.get('SUPABASE_ANON_KEY')!,secret=Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
  const authorization=req.headers.get('authorization')||'';
  const ah={authorization,apikey:anon};
  const auth=await fetch(base+'/auth/v1/user',{headers:ah});if(!auth.ok)return reply(401,{error:'再ログインしてください'});
  const user=await auth.json();
  const mr=await fetch(base+'/rest/v1/sumdex_members?select=role,active&email=eq.'+encodeURIComponent(user.email?.toLowerCase()||''),{headers:ah});
  const members=mr.ok?await mr.json():[];if(!members.some((m:any)=>m.active))return reply(403,{error:'利用登録が必要です'});
  const db=async(path:string,method='GET',body?:unknown)=>{const r=await fetch(base+'/rest/v1/'+path,{method,headers:{apikey:secret,authorization:'Bearer '+secret,'content-type':'application/json',Prefer:'return=representation,resolution=merge-duplicates'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw Error('共有データの保存・読み込みに失敗しました');return r.status===204?[]:await r.json();};
  const raw=await req.text();if(raw.length>200000)return reply(413,{error:'入力が大きすぎます'});const b=JSON.parse(raw);
  const config=(await db('sumdex_post_config?id=eq.true'))[0]?.data;
  const destination=config?{name:config.name,channelId:config.channelId,guildId:config.guildId}:null;
  if(b.action==='status')return reply(200,{destination});
  if(b.action==='configure'){
   if(!members.some((m:any)=>m.active&&m.role==='admin'))return reply(403,{error:'管理者だけが設定できます'});
   const u=new URL(String(b.url));if(u.origin!=='https://discord.com'||!/^\/api(?:\/v10)?\/webhooks\/\d+\/[A-Za-z0-9_-]+$/.test(u.pathname)||u.search||u.hash)throw Error('DiscordのWebhook URLを入力してください');
   const check=await fetch(u,{signal:AbortSignal.timeout(10000)});if(!check.ok)throw Error('Webhookを確認できません。URLを確認してください');const hook=await check.json();
   if(hook.type!==1||!hook.channel_id||!hook.guild_id)throw Error('サーバーのテキストチャンネル用Webhookを使用してください');
   await db('sumdex_post_config','POST',{id:true,data:{url:u.href,name:hook.name,channelId:hook.channel_id,guildId:hook.guild_id}});
   return reply(200,{destination:{name:hook.name,channelId:hook.channel_id,guildId:hook.guild_id}});
  }
  if(b.action==='image'){
   const u=new URL(String(b.url));if(u.protocol!=='https:'||u.hostname!=='cdn.snkrdunk.com'||u.username||u.password||u.port)throw Error('URL取り込みはcdn.snkrdunk.comに対応しています。他の画像はファイルを選んでください');
   const r=await fetch(u,{redirect:'error',signal:AbortSignal.timeout(15000)});if(!r.ok||!/^image\/(webp|png|jpeg)(;|$)/i.test(r.headers.get('content-type')||''))throw Error('画像を取得できません。ファイルを選んでください');
   const reader=r.body!.getReader(),chunks:Uint8Array[]=[];let size=0;
   while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>10*1024*1024){await reader.cancel();throw Error('画像は10MB以下にしてください');}chunks.push(value);}
   const data=new Uint8Array(size);let offset=0;for(const c of chunks){data.set(c,offset);offset+=c.length;}let binary='';for(let i=0;i<data.length;i+=8192)binary+=String.fromCharCode(...data.subarray(i,i+8192));
   return reply(200,{image:'data:'+r.headers.get('content-type')!.split(';')[0]+';base64,'+btoa(binary)});
  }
  if(!config)throw Error('先に「投稿先の設定」で販売用Webhookを登録してください');
  const validate=async(rows:any[])=>{
   const docs=await db('sumdex_documents?id=in.(catalog,settings)');const catalog=docs.find((d:any)=>d.id==='catalog')?.data.products||[],settings=docs.find((d:any)=>d.id==='settings')?.data||{};
   if(!Array.isArray(rows)||!rows.length||rows.length>300)throw Error('掲載行を確認してください');
   const selected=[...new Set(rows.map(r=>r.productId))].map(id=>catalog.find((p:any)=>p.id===id));if(selected.some(p=>!p))throw Error('商品が削除されました。確認画面を作り直してください');
   const sources=[...new Set(selected.flatMap(p=>sourceKey(p.sourceUrl)?[sourceKey(p.sourceUrl)]:['pokemon','onepiece']))];
   const lists=await Promise.all(sources.map(s=>fetchNotionSource(s)));
   for(const p of selected){const hit=matchLiveProduct(p,lists);if(hit.row.price!==p.price)throw Error('SUMdex価格が変更されました。価格を確認してプレビューを作り直してください');}
   return buildMessages(rows,catalog,settings,base+'/storage/v1/object/public/sumdex-products/');
  };
  if(b.action==='prepare'){
   const messages=await validate(b.rows),id=crypto.randomUUID();await db('sumdex_posts','POST',{id,owner:user.id,data:{rows:b.rows,messages,destination,configUrl:config.url}});
   return reply(200,{id,messages,destination});
  }
  if(b.action==='post'){
   if(!/^[\da-f-]{36}$/.test(String(b.id)))throw Error('確認画面を作り直してください');
   const path='sumdex_posts?id=eq.'+b.id+'&owner=eq.'+user.id;const post=(await db(path))[0];if(!post)throw Error('確認画面が見つかりません');
   if(post.state!=='ready')return reply(200,{state:post.state,links:post.data.links||[],error:post.state==='sent'?null:'送信済み・送信中、または結果が未確定です。Discordを確認してください。自動再送はしません。'});
   if(Date.now()-Date.parse(post.created_at)>10*60*1000)throw Error('確認画面の有効期限（10分）が切れました。作り直してください');
   if(post.data.configUrl!==config.url)throw Error('投稿先が変わりました。確認画面を作り直してください');
   const messages=await validate(post.data.rows);if(JSON.stringify(messages)!==JSON.stringify(post.data.messages))throw Error('商品情報が変更されました。確認画面を作り直してください');
   const locked=await db(path+'&state=eq.ready','PATCH',{state:'sending'});if(!locked.length)throw Error('すでに送信処理を開始しています');
   const links:string[]=[];
   try{
    for(const message of messages){
     const r=await fetch(config.url+'?wait=true',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(message),signal:AbortSignal.timeout(20000)});
     if(!r.ok)throw Error('Discord側で受け付けられませんでした');const result=await r.json();if(!result.id)throw Error('送信結果が確認できません');
     links.push(`https://discord.com/channels/${config.guildId}/${config.channelId}/${result.id}`);
     await db(path,'PATCH',{data:{...post.data,links}});
     if(messages.length>1)await new Promise(resolve=>setTimeout(resolve,600));
    }
    await db(path,'PATCH',{state:'sent',data:{...post.data,links}});return reply(200,{state:'sent',links});
   }catch{await db(path,'PATCH',{state:'uncertain',data:{...post.data,links}});return reply(200,{state:'uncertain',links,error:'一部送信済み、または結果を確認できません。Discordで確認してください。重複を防ぐため、この投稿は再送しません。'});}
  }
  throw Error('操作を確認してください');
 }catch(e){return reply(400,{error:e instanceof Error?e.message:'処理できませんでした'});}
});
