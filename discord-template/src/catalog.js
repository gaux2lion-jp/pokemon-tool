import {nameKey,parseCSV} from './pricing.js';

export const CSV_KEYS=['id','ja','en','code','domesticNames','price','sourceUrl','checkedAt','notionRowId'];

export function validateCatalog(products){
 const names=new Map();
 for(const p of products){
  if(!p.ja||(!p.en&&!p.code))throw Error(`「${p.ja||'商品名未入力'}」：国内商品名と、英語名または型番を入力してください`);
  for(const name of [p.ja,...String(p.domesticNames||'').split('|')]){
   const key=nameKey(name);if(!key)continue;
   if(names.has(key)&&names.get(key)!==p.id)throw Error(`国内価格表の日本語名が複数の商品と一致します：${name}`);
   names.set(key,p.id);
  }
  if(p.price!==''&&p.price!=null&&(!Number.isFinite(p.price)||p.price<=0))throw Error(`「${p.ja}」：SUMdex価格は正の数値を入力してください`);
  if(p.sourceUrl&&!/^https:\/\//.test(p.sourceUrl))throw Error(`「${p.ja}」：価格表URLを確認してください`);
  if(p.checkedAt&&!Number.isFinite(Date.parse(p.checkedAt)))throw Error(`「${p.ja}」：確認日時を確認してください`);
  if(p.checkedAt&&(!p.price||!p.sourceUrl))throw Error(`「${p.ja}」：確認日時がある商品は価格と価格表URLが必要です`);
  if(p.notionRowId&&!/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(p.notionRowId))throw Error(`「${p.ja}」：Notion商品IDを確認してください`);
 }
}

export function planCatalogImport(text,catalog,idFactory){
 const [header,...data]=parseCSV(text.replace(/^\ufeff/,''));
 if(!header||CSV_KEYS.filter(k=>!['domesticNames','notionRowId'].includes(k)).some(k=>!header.includes(k)))throw Error('CSVの列が不足しています。書き出したCSVを使ってください');
 const next=structuredClone(catalog),seen=new Set();let added=0,updated=0,skipped=0;
 data.forEach((row,index)=>{
  const p=Object.fromEntries(CSV_KEYS.map(k=>[k,header.includes(k)?(row[header.indexOf(k)]||'').trim():'']));
  const selected=['id','en','code','domesticNames','price','sourceUrl','checkedAt','notionRowId'].some(k=>p[k]);
  if(!selected){skipped++;return;}
  const line=index+2;
  if(!p.ja||(!p.en&&!p.code))throw Error(`CSV ${line}行目：国内商品名と、英語名または型番を入力してください`);
  p.price=p.price?Number(p.price):'';
  if(p.price!==''&&(!Number.isFinite(p.price)||p.price<=0))throw Error(`CSV ${line}行目：SUMdex価格を確認してください`);
  if(p.sourceUrl&&!/^https:\/\//.test(p.sourceUrl))throw Error(`CSV ${line}行目：価格表URLを確認してください`);
  if(p.checkedAt&&!Number.isFinite(Date.parse(p.checkedAt)))throw Error(`CSV ${line}行目：確認日時の形式を確認してください`);
  const identity=p.id||nameKey(p.ja);
  if(seen.has(identity))throw Error(`CSV ${line}行目：同じ商品がCSV内で重複しています`);
  seen.add(identity);
  const i=next.findIndex(x=>p.id?x.id===p.id:nameKey(x.ja)===nameKey(p.ja));
  if(i>=0){
   if(!header.includes('domesticNames'))p.domesticNames=next[i].domesticNames||'';
   if(!header.includes('notionRowId'))p.notionRowId=next[i].notionRowId||'';
   if(next[i].sourceUrl!==p.sourceUrl)p.notionRowId='';
   if(next[i].price!==p.price||next[i].sourceUrl!==p.sourceUrl)p.checkedAt='';
   else if(!p.checkedAt)p.checkedAt=next[i].checkedAt||'';
   p.id=next[i].id;next[i]=p;updated++;
  }else{p.id=p.id||idFactory();next.push(p);added++;}
 });
 if(added+updated)validateCatalog(next);
 return {products:next,added,updated,skipped};
}
