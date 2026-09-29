export const CONDITIONS = {
 sa:['S・A','Clean packaging with no holes or dents.'],
 am:['AM','The packaging has a dent or hole.'],
 b:['B','The packaging has a major dent or large hole.']
};
export const DEFAULTS={sa:100,am:700,b:1500};
const CONDITION_ORDER={sa:0,am:1,b:2};
const CONDITION_MARKS={sa:'🟢',am:'🟡',b:'🔴'};
const LEGACY_DEFAULTS={clean:100,shrinkSmall:300,shrinkLarge:500,dentSmall:500,dentLarge:1000,stainSmall:300,stainLarge:700};
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
 if(!checked)return current?.length?current:['sa'];
 return CONDITIONS[key]?[key]:['sa'];
}
export function conditionKey(row){
 const selected=Array.isArray(row?.conditions)?row.conditions:[];
 const current=selected.find(key=>CONDITIONS[key]);if(current)return current;
 if(selected.some(key=>/Large$/.test(key)))return 'b';
 if(selected.some(key=>key!=='clean'))return 'am';
 return 'sa';
}
export function normalizeConditionRow(row,settings={}){
 const selected=Array.isArray(row?.conditions)?row.conditions:[];
 const grade=conditionKey(row);
 if(selected.length===1&&selected[0]===grade)return {...row,conditions:[grade],discounts:{...(row.discounts||{})}};
 const legacySettings={...LEGACY_DEFAULTS,...settings};
 const base=row?.discounts?.clean??legacySettings.clean;
 const extra=selected.filter(key=>key!=='clean').reduce((sum,key)=>sum+(row?.discounts?.[key]??legacySettings[key]??0),0);
 return {...row,conditions:[grade],discounts:{[grade]:base+extra}};
}
function calculateWithBasis(row,product,settings,domestic,basis){
 const sumdex=product?.price; const validPrice=Number.isFinite(sumdex)&&sumdex>0;
 const grade=conditionKey(row);
 const discount=Number(row.discounts?.[grade]??settings[grade]??DEFAULTS[grade]??0);
 const highest=domestic?.shops?.length?Math.max(...domestic.shops.map(s=>s.price)):null;
 const suggested=validPrice?Math.max(0,sumdex-discount):null;
 const target=basis==='domestic'&&highest!==null&&suggested!==null?Math.max(highest,suggested):suggested;
 const sale=row.manualPrice!==''&&row.manualPrice!=null?Number(row.manualPrice):target;
 const cost=Number(row.cost), expenses=Number(row.expenses||0);
 const refund=cost/11; const profit=sale==null?null:sale-cost+refund-expenses;
 const errors=[];
 if(!product?.en||!product?.code)errors.push('英語名・型番の対応付けが必要');
 if(!validPrice)errors.push('SUMdex価格が未入力：商品名・価格表で登録してください');
 if(!row.cost||!Number.isFinite(cost)||cost<=0||!Number.isFinite(expenses)||expenses<0)errors.push('仕入れ値・費用を確認');
 if(!Number.isFinite(sale)||sale<=0)errors.push('販売価格を確認');
 if(validPrice&&sale>sumdex)errors.push('SUMdex価格を超過：価格変更または掲載対象外を選択');
 if(profit!==null&&profit < -0.000001&&!row.allowLoss)errors.push('還付込みでも赤字：赤字で掲載する場合は確認チェックを入れてください');
 if(basis==='domestic'&&highest===null)errors.push('国内買取価格を取得できていません');
 return {sale,profit,refund,discount,damage:grade==='sa'?0:discount,grade,highest,sumdex,errors,actualDiscount:validPrice?sumdex-sale:null,basis};
}
export function recommendPriceBasis(row,product,settings,domestic){
 const candidate={...row,manualPrice:''};
 const sumdex=calculateWithBasis(candidate,product,settings,domestic,'sumdex');
 const domesticFloor=calculateWithBasis(candidate,product,settings,domestic,'domestic');
 const valid=result=>Number.isFinite(result.sale)&&result.sale>0&&result.profit>=0&&(!Number.isFinite(result.sumdex)||result.sale<=result.sumdex);
 if(!Number.isFinite(sumdex.sumdex)||sumdex.sumdex<=0)return {basis:'sumdex',status:'waiting',title:'SUMdex価格の確認待ち',reason:'商品を選ぶとNotion価格表を確認します。',sumdex,domesticFloor};
 if(valid(sumdex)&&(sumdex.highest===null||sumdex.sale>=sumdex.highest))return {basis:'sumdex',status:'ready',title:'SUMdexから割引がおすすめ',reason:sumdex.highest===null?'国内価格が未確認のため、SUMdex価格から状態別に値引きします。':'割引後も国内最高表示額以上で、還付込み利益も残ります。',sumdex,domesticFloor};
 if(valid(domesticFloor)&&domesticFloor.sale<=domesticFloor.sumdex)return {basis:'domestic',status:'ready',title:'国内最高表示額を下回らない設定がおすすめ',reason:'SUMdexの上限内で国内最高表示額を維持できます。国内買取は状態による減額があるため確約ではありません。',sumdex,domesticFloor};
 if(valid(sumdex))return {basis:'sumdex',status:'caution',title:'SUMdexから割引を使用',reason:'国内最高表示額の方が高いため国内販売も比較してください。ただし、国内買取は状態による減額があり満額保証ではありません。',sumdex,domesticFloor};
 if(row.allowLoss&&sumdex.profit<0)return {basis:'sumdex',status:'caution',title:'赤字で掲載する設定',reason:`還付を含めても${yen(Math.abs(sumdex.profit))}の赤字です。確認チェックが入っているため投稿文を作成できます。`,sumdex,domesticFloor};
 return {basis:'sumdex',status:'stop',title:'掲載しないのがおすすめ',reason:'SUMdex価格から状態別に値引きすると、還付を含めても赤字になります。販売価格を見直すか、赤字を確認して掲載を許可してください。',sumdex,domesticFloor};
}
export function calculate(row,product,settings,domestic){
 const basis=row.basis==='auto'?recommendPriceBasis(row,product,settings,domestic).basis:row.basis;
 return calculateWithBasis(row,product,settings,domestic,basis);
}
const safe=s=>String(s??'').replace(/[\\`*_~|<>@]/g,'').replace(/[\r\n]+/g,' ').trim();
export function generate(rows,catalog,settings,domestic){
 const groups=new Map(); const errors=[];
 for(const row of rows.filter(r=>r.include)){
  const product=catalog.find(p=>p.id===row.productId); const c=calculate(row,product,settings,domesticForProduct(domestic,product));
  if(c.errors.length){errors.push(...c.errors.map(e=>`${product?.ja||'商品未選択'}：${e}`));continue;}
  const key=`${product.id}:${Number(row.cost)}`;
  if(!groups.has(key))groups.set(key,{product,lines:[]});
  const grade=conditionKey(row),conditions=CONDITIONS[grade][1];
  const discount=c.actualDiscount>0?` (${yen(c.actualDiscount)} off listed price)`:'';
  groups.get(key).lines.push({grade,text:`• ${CONDITION_MARKS[grade]} **${grade==='sa'?'S/A':CONDITIONS[grade][0]}** — ${conditions}${row.notes?` ${safe(row.notes)}`:''}\n  **${yen(c.sale)} / BOX**${discount}`});
 }
 const blocks=[...groups.values()].map(({product,lines})=>{const ordered=[...new Map(lines.map(line=>[line.text,line])).values()].sort((a,b)=>CONDITION_ORDER[a.grade]-CONDITION_ORDER[b.grade]);return `**${safe(product.en)} [${safe(product.code)}]**\nListed price: ${yen(product.price)} / BOX\n${ordered.map(line=>line.text).join('\n')}`;});
 const text=blocks.length?`🇯🇵 **SUMdex · Discord Offers**\n\n${blocks.join('\n\n')}\n\n📸 Photos and videos of the actual condition are available before purchase.\n🎫 Please open a ticket to order, ask about other products, or discuss preorders.\nShipping and payment fees will be confirmed in your ticket.`:'';
 return {text,errors};
}
export function parseCSV(text){
 const rows=[];let row=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(Boolean))rows.push(row);row=[];field='';}else field+=c;}
 if(quoted)throw Error('CSVの引用符が閉じていません');row.push(field);if(row.some(Boolean))rows.push(row);return rows;
}
