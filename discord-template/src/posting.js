import {categoryOf} from './domestic.js';
import {calculate,conditionKey,yen} from './pricing.js';
const order={sa:0,am:1,b:2},marks={sa:'🟢 S/A',am:'🟡 AM',b:'🔴 B'};
const safe=s=>String(s??'').replace(/[\\`*_~|<>@]/g,'').replace(/[\r\n]+/g,' ').trim();
export const TICKET='https://discord.com/channels/1540333224570519655/1540439626647609344/1540468517579657359';
export function buildMessages(rows,catalog,settings,imageBase){
 if(!Array.isArray(rows)||!rows.length||rows.length>300)throw Error('掲載行は1〜300行にしてください');
 const groups=new Map();
 for(const row of rows){
  const p=catalog.find(p=>p.id===row.productId);
  if(!Number.isSafeInteger(Number(row.manualPrice)))throw Error('販売価格は整数で指定してください');
  const c=calculate({...row,include:true,basis:'sumdex'},p,settings,null);
  if(c.errors.length)throw Error(`${p?.ja||'商品未選択'}：${c.errors.join(' ／ ')}`);
  if(String(row.notes||'').length>300)throw Error('状態の補足は300文字以内にしてください');
  const grade=conditionKey(row);
  if(!groups.has(p.id))groups.set(p.id,{p,lines:[]});
  groups.get(p.id).lines.push({grade,text:`${marks[grade]}  **${yen(c.sale)}**${c.actualDiscount>0?` · −${yen(c.actualDiscount)}`:''}${row.notes?`\n${safe(row.notes)}`:''}`});
 }
 const products=[...groups.values()].map(({p,lines})=>{
  const title=`${categoryOf(p)==='pokemon'?'Pokémon Card · ':categoryOf(p)==='onepiece'?'ONE PIECE Card · ':''}${safe(p.en)}${safe(p.code)?` [${safe(p.code)}]`:''}`;
  const description=`SUMdex List: ${yen(p.price)}\n\n`+[...new Map(lines.map(l=>[l.text,l])).values()].sort((a,b)=>order[a.grade]-order[b.grade]).map(l=>l.text).join('\n');
  if(title.length>256||description.length>3000)throw Error(`${p.ja}：説明が長いため行を減らしてください`);
  const embed={title,description,color:0x176451};
  if(p.imagePath){if(!/^[a-zA-Z0-9_/-]+\.webp$/.test(p.imagePath))throw Error('商品画像を再登録してください');embed.thumbnail={url:imageBase+p.imagePath};}
  return embed;
 });
 const footer={title:'📋 Condition Guide',description:`🟢 **S/A** — S: No holes or dents. A: Very minor imperfections.\n🟡 **AM** — Light dents or holes.\n🔴 **B** — Major dents / shrink-wrap holes or tears; may be worse than examples.\n📸 Reference images. Ask for actual-box photos/videos.\n🎫 **[Order / Ask us here](${TICKET})** · Preorders welcome!\n🚚 Shipping & payment fees quoted separately.`};
 const batches=[];let embeds=[],chars=footer.title.length+footer.description.length;
 for(const p of products){const n=p.title.length+p.description.length;if(embeds.length>=8||chars+n>5800){batches.push(embeds);embeds=[];chars=footer.title.length+footer.description.length;}embeds.push(p);chars+=n;}
 if(embeds.length)batches.push(embeds);
 return batches.map((batch,i)=>({content:`${i===0?'🔥 **DISCORD-EXCLUSIVE BOX DEALS**\n🇯🇵 JPY / BOX · **Discord price** · −Discount': '🇯🇵 SUMdex · Discord Offers'}${batches.length>1?`\n${i+1} / ${batches.length}`:''}`,embeds:i===batches.length-1?[...batch,footer]:batch,allowed_mentions:{parse:[]}}));
}

// Accept text edits only. Images, mention rules and message structure stay server-controlled.
export function applyTextEdits(original,edited){
 if(!Array.isArray(edited)||edited.length!==original.length)throw Error('投稿の構成が変わりました。確認画面を作り直してください');
 return original.map((m,i)=>{
  const e=edited[i];if(!e||typeof e.content!=='string'||e.content.length>2000||!Array.isArray(e.embeds)||e.embeds.length!==m.embeds.length)throw Error('冒頭の文章は2,000文字以内にしてください');
  let count=0;const embeds=m.embeds.map((embed,j)=>{
   const x=e.embeds[j];if(!x||typeof x.title!=='string'||!x.title.trim()||x.title.length>256||typeof x.description!=='string'||!x.description.trim()||x.description.length>4096)throw Error('見出しは1〜256文字、本文は1〜4,096文字にしてください');
   count+=x.title.length+x.description.length;return {...embed,title:x.title,description:x.description};
  });
  if(count>6000)throw Error(`メッセージ${i+1}の見出し・本文が合計6,000文字を超えています。短くするか商品を分けてください`);
  return {...m,content:e.content,embeds,allowed_mentions:{parse:[]}};
 });
}
