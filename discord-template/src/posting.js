import {calculate,conditionKey,CONDITIONS,yen} from './pricing.js';
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
  groups.get(p.id).lines.push({grade,text:`**${marks[grade]}**\n${yen(p.price)} → **${yen(c.sale)}**${c.actualDiscount>0?`\n💸 **${yen(c.actualDiscount)} OFF**`:''}${row.notes?`\n${safe(row.notes)}`:''}`});
 }
 const products=[...groups.values()].map(({p,lines})=>{
  const title=`✨ ${safe(p.en)}${safe(p.code)?` [${safe(p.code)}]`:''}`;
  const description=[...new Map(lines.map(l=>[l.text,l])).values()].sort((a,b)=>order[a.grade]-order[b.grade]).map(l=>l.text).join('\n\n');
  if(title.length>256||description.length>3000)throw Error(`${p.ja}：説明が長いため行を減らしてください`);
  const embed={title,description,color:0x176451};
  if(p.imagePath){if(!/^[a-zA-Z0-9_/-]+\.webp$/.test(p.imagePath))throw Error('商品画像を再登録してください');embed.image={url:imageBase+p.imagePath};}
  return embed;
 });
 const footer={title:'📋 Condition Guide',description:`🟢 **S/A** — S: No holes or dents. A: Only very minor imperfections.\n🟡 **AM** — Light dents or holes.\n🔴 **B** — Major dents or shrink-wrap holes/tears; may be worse than guide examples.\n\nProduct images are for reference. Request actual-box photos/videos before purchase.\n\n🎫 **[Order / Ask us here](${TICKET})**\nPreorders & product requests welcome!\n🚚 Shipping & payment fees quoted separately.`};
 const batches=[];let embeds=[],chars=footer.title.length+footer.description.length;
 for(const p of products){const n=p.title.length+p.description.length;if(embeds.length>=8||chars+n>5800){batches.push(embeds);embeds=[];chars=footer.title.length+footer.description.length;}embeds.push(p);chars+=n;}
 if(embeds.length)batches.push(embeds);
 return batches.map((batch,i)=>({content:`🔥 **DISCORD-EXCLUSIVE BOX DEALS**\n🇯🇵 **JPY / BOX** · SUMdex list price → **Discord price**${batches.length>1?`\n${i+1} / ${batches.length}`:''}`,embeds:[...batch,footer],allowed_mentions:{parse:[]}}));
}
