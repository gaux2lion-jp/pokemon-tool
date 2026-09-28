export const CONDITIONS = {
 clean:['問題なく綺麗','Clean packaging; no noticeable damage.'],
 shrinkSmall:['シュリンク穴 小','Small hole in the shrink wrap.'],
 shrinkLarge:['シュリンク穴 大','Large hole or tear in the shrink wrap.'],
 dentSmall:['潰れ 小','Minor dent on the box.'],
 dentLarge:['潰れ 大','Noticeable dent or crushing on the box.'],
 stainSmall:['汚れ 小','Small stain on the packaging.'],
 stainLarge:['汚れ 大','Noticeable stain on the packaging.']
};
export const DEFAULTS={clean:100,shrinkSmall:300,shrinkLarge:500,dentSmall:500,dentLarge:1000,stainSmall:300,stainLarge:700};
export const yen=n=>`¥${Math.round(n).toLocaleString('en-US')}`;
export const nameKey=name=>String(name??'').normalize('NFKC').trim().replace(/\s+/g,' ').toLowerCase();
export const productNames=product=>[product.ja,product.en,...String(product.domesticNames||'').split('|')].map(s=>s.trim()).filter(Boolean);
export function domesticForProduct(domestic,product){
 if(!product)return null;
 const names=new Set([product.ja,...String(product.domesticNames||'').split('|')].map(nameKey).filter(Boolean));
 const matched=Object.entries(domestic||{}).filter(([name])=>names.has(nameKey(name)));
 return matched.length?{shops:matched.flatMap(([,entry])=>entry.shops||[])}:null;
}
export function toggleCondition(current,key,checked){
 if(!checked){const next=current.filter(k=>k!==key);return next.length?next:['clean'];}
 if(key==='clean')return ['clean'];
 const family=key.replace(/Small|Large/,'');
 return [...current.filter(k=>k!=='clean'&&k.replace(/Small|Large/,'')!==family),key];
}
export function calculate(row,product,settings,domestic){
 const sumdex=product?.price; const validPrice=Number.isFinite(sumdex)&&sumdex>0;
 const damage=row.conditions.filter(k=>k!=='clean').reduce((n,k)=>n+(row.discounts?.[k]??settings[k]??0),0);
 const discount=(row.discounts?.clean??settings.clean??100)+damage;
 const highest=domestic?.shops?.length?Math.max(...domestic.shops.map(s=>s.price)):null;
 const suggested=validPrice?Math.max(0,sumdex-discount):null;
 const target=row.basis==='domestic'&&highest!==null&&suggested!==null?Math.max(highest,suggested):suggested;
 const sale=row.manualPrice!==''&&row.manualPrice!=null?Number(row.manualPrice):target;
 const cost=Number(row.cost), expenses=Number(row.expenses||0);
 const refund=cost/11; const profit=sale==null?null:sale-cost+refund-expenses;
 const errors=[];
 if(!product?.en||!product?.code)errors.push('英語名・型番の対応付けが必要');
 if(!validPrice)errors.push('SUMdex価格が未入力：商品名・価格表で登録してください');
 if(!row.cost||!Number.isFinite(cost)||cost<=0||!Number.isFinite(expenses)||expenses<0)errors.push('仕入れ値・費用を確認');
 if(!Number.isFinite(sale)||sale<=0)errors.push('販売価格を確認');
 if(validPrice&&sale>sumdex)errors.push('SUMdex価格を超過：価格変更または掲載対象外を選択');
 if(profit!==null&&profit < -0.000001)errors.push('還付込みでも赤字：価格変更または掲載対象外を選択');
 if(row.basis==='domestic'&&highest===null)errors.push('国内買取価格を取得できていません');
 return {sale,profit,refund,discount,damage,highest,sumdex,errors,actualDiscount:validPrice?sumdex-sale:null};
}
const safe=s=>String(s??'').replace(/[\\`*_~|<>@]/g,'').replace(/[\r\n]+/g,' ').trim();
export function generate(rows,catalog,settings,domestic){
 const groups=new Map(); const errors=[];
 for(const row of rows.filter(r=>r.include)){
  const product=catalog.find(p=>p.id===row.productId); const c=calculate(row,product,settings,domesticForProduct(domestic,product));
  if(c.errors.length){errors.push(...c.errors.map(e=>`${product?.ja||'商品未選択'}：${e}`));continue;}
  const key=`${product.id}:${Number(row.cost)}`;
  if(!groups.has(key))groups.set(key,{product,lines:[]});
  const conditions=row.conditions.map(k=>CONDITIONS[k][1]).join(' ');
  const discount=c.actualDiscount>0?` (${yen(c.actualDiscount)} off listed price)`:'';
  groups.get(key).lines.push(`• ${conditions}${row.notes?` ${safe(row.notes)}`:''}\n  **${yen(c.sale)} / BOX**${discount}`);
 }
 const blocks=[...groups.values()].map(({product,lines})=>`**${safe(product.en)} [${safe(product.code)}]**\nListed price: ${yen(product.price)} / BOX\n${[...new Set(lines)].join('\n')}`);
 const text=blocks.length?`🇯🇵 **SUMdex · Discord Offers**\n\n${blocks.join('\n\n')}\n\n📸 Photos and videos of the actual condition are available before purchase.\n🎫 Please open a ticket to order, ask about other products, or discuss preorders.\nShipping and payment fees will be confirmed in your ticket.`:'';
 return {text,errors};
}
export function parseCSV(text){
 const rows=[];let row=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(Boolean))rows.push(row);row=[];field='';}else field+=c;}
 if(quoted)throw Error('CSVの引用符が閉じていません');row.push(field);if(row.some(Boolean))rows.push(row);return rows;
}
