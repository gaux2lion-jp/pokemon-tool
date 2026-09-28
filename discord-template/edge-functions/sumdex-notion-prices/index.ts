import {fetchNotionSource,SOURCES} from './notion.js';

const origin='https://gaux2lion-jp.github.io';
const headers={'content-type':'application/json','access-control-allow-origin':origin,'access-control-allow-headers':'authorization,apikey,content-type,x-client-info','access-control-allow-methods':'POST,OPTIONS','cache-control':'no-store'};
const reply=(status:number,body:unknown)=>new Response(JSON.stringify(body),{status,headers});

Deno.serve(async(req:Request)=>{
 if(req.method==='OPTIONS')return new Response(null,{status:204,headers});
 if(req.method!=='POST')return reply(405,{error:'POSTのみ対応します'});
 const base=Deno.env.get('SUPABASE_URL'),key=Deno.env.get('SUPABASE_ANON_KEY');
 if(!base||!key)return reply(503,{error:'認証設定が不足しています'});
 const authorization=req.headers.get('authorization')||'';
 if(!/^Bearer \S+$/.test(authorization))return reply(401,{error:'ログインしてください'});
 try{
  const authHeaders={authorization,apikey:key};
  const auth=await fetch(`${base}/auth/v1/user`,{headers:authHeaders});
  if(!auth.ok)return reply(401,{error:'ログインを確認できません'});
  const user=await auth.json();
  if(!user?.email)return reply(403,{error:'利用者を確認できません'});
  const members=await fetch(`${base}/rest/v1/sumdex_members?select=active&email=eq.${encodeURIComponent(user.email.toLowerCase())}`,{headers:authHeaders});
  if(!members.ok||!(await members.json()).some((member:{active:boolean})=>member.active))return reply(403,{error:'このアカウントは利用登録されていません'});
  const body=await req.json();
  if(!Array.isArray(body.sources)||!body.sources.length||body.sources.length>2||body.sources.some((source:unknown)=>typeof source!=='string'||!Object.hasOwn(SOURCES,source)))return reply(400,{error:'価格表の指定を確認してください'});
  const lists=await Promise.all([...new Set(body.sources)].map((source:string)=>fetchNotionSource(source)));
  return reply(200,{lists});
 }catch(error){
  console.error('Notion price check failed',error);
  return reply(502,{error:'Notion価格表を読み取れませんでした。価格を推測せず、掲載を停止します。時間を置いて再試行してください。'});
 }
});
