const CONDITION_RULES={
  clean:{label:'問題なく綺麗',discount:100,group:'good',en:'No noticeable damage.'},
  shrinkSmall:{label:'シュリンク穴・小',discount:300,group:'shrink',en:'Small hole in the shrink wrap.'},
  shrinkLarge:{label:'シュリンク穴・大',discount:500,group:'shrink',en:'Large hole or tear in the shrink wrap.'},
  dentSmall:{label:'潰れ・小',discount:500,group:'box',en:'Minor dent on the box.'},
  dentLarge:{label:'潰れ・大',discount:1000,group:'heavy',en:'Noticeable dent or crushing on the box.'},
  stainSmall:{label:'汚れ・小',discount:300,group:'box',en:'Small stain on the outer package.'},
  stainLarge:{label:'汚れ・大',discount:700,group:'heavy',en:'Noticeable staining on the outer package.'}
};
const STORAGE_KEY='sumdex-discord-builder-v1';
const PRICE_KEY='sumdex-price-master-v1';
let domesticProducts={};
let items=[];
const $=id=>document.getElementById(id);
const yen=value=>`¥${Math.round(Number(value)||0).toLocaleString('ja-JP')}`;
const roundUp100=value=>Math.ceil(value/100)*100;
const uid=()=>`${Date.now()}-${Math.random().toString(16).slice(2)}`;

function getPriceMaster(){try{return JSON.parse(localStorage.getItem(PRICE_KEY)||'{}')}catch{return{}}}
function savePrice(name,price){const master=getPriceMaster();master[name]=Number(price);localStorage.setItem(PRICE_KEY,JSON.stringify(master))}
function saveItems(){localStorage.setItem(STORAGE_KEY,JSON.stringify(items))}
function loadItems(){try{items=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]')}catch{items=[]}}

async function loadDomesticPrices(){
  try{
    const response=await fetch('../index.html',{cache:'no-store'});
    if(!response.ok)throw new Error('価格一覧を取得できませんでした');
    const doc=new DOMParser().parseFromString(await response.text(),'text/html');
    const rows=[...doc.querySelectorAll('table tr')];
    let current=null;
    for(const row of rows){
      if(row.classList.contains('product-row')){
        const name=row.querySelector('strong')?.textContent.trim();
        if(!name)continue;
        current={name,shops:[]};domesticProducts[name]=current;
      }else if(current){
        const cells=row.querySelectorAll('td');if(cells.length<3)continue;
        const site=(cells[0].childNodes[0]?.textContent||cells[0].textContent).trim();
        const price=Number((cells[2].textContent.match(/[\d,]+/)||['0'])[0].replaceAll(',',''));
        const guarantee=/満額保証|減額なし/.test(cells[0].textContent);
        if(price)current.shops.push({site,price,guarantee});
      }
    }
    const names=Object.keys(domesticProducts).sort((a,b)=>a.localeCompare(b,'ja'));
    $('productOptions').innerHTML=names.map(name=>`<option value="${escapeHtml(name)}"></option>`).join('');
    $('dataStatus').className='status ready';$('dataStatus').textContent=`国内価格 ${names.length}商品 読込済み`;
  }catch(error){
    $('dataStatus').className='status error';$('dataStatus').textContent='国内価格の読込失敗';
  }
  render();
}

function escapeHtml(value){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function selectedConditions(){return [...$('conditionOptions').querySelectorAll('input:checked')].map(input=>input.value)}
function domesticInfo(name){
  const shops=domesticProducts[name]?.shops||[];
  const highest=shops.reduce((best,s)=>!best||s.price>best.price?s:best,null);
  const guaranteed=shops.filter(s=>s.guarantee).reduce((best,s)=>!best||s.price>best.price?s:best,null);
  return {highest,guaranteed,reference:guaranteed||highest};
}
function calculate(item){
  const cap=Number($('discountCap').value)||0;
  const minProfit=Number($('minimumProfit').value)||0;
  const discount=Math.min(item.conditions.reduce((sum,key)=>sum+(CONDITION_RULES[key]?.discount||0),0),cap);
  const suggested=Math.max(0,item.sumdexPrice-discount);
  const salePrice=Math.min(item.sumdexPrice,Number(item.salePrice??suggested));
  const refund=item.purchasePrice*10/110;
  const netCost=item.purchasePrice-refund;
  const profit=salePrice-netCost-item.expenses;
  const domestic=domesticInfo(item.name);
  let level='ideal',decision='販売推奨';
  if(profit<=0){level='loss';decision='赤字・掲載非推奨'}
  else if(profit<minProfit||domestic.reference&&salePrice<domestic.reference.price){level='review';decision='要検討'}
  return {...item,discount,suggested,salePrice,refund,netCost,profit,domestic,level,decision,minProfit};
}

function conditionGroup(item){
  const groups=item.conditions.map(k=>CONDITION_RULES[k]?.group);
  if(groups.includes('heavy')||item.conditions.length>1)return'heavy';
  return groups[0]||'good';
}

function render(){
  $('emptyState').hidden=items.length>0;
  $('items').innerHTML=items.map(raw=>{
    const item=calculate(raw);const ref=item.domestic.reference;
    const conditionLabels=item.conditions.map(k=>CONDITION_RULES[k]?.label).join('・');
    const warning=item.level==='loss'?'現在の販売価格では赤字のため、初期状態では掲載対象外です。':item.level==='review'?'国内売却見込または最低必要利益を下回るため、掲載前に確認してください。':'';
    return `<article class="item ${item.level}">
      <div class="item-head"><div><h3>${escapeHtml(item.name)}</h3><div class="badges"><span class="badge">${escapeHtml(conditionLabels)}</span><span class="badge">${item.quantity} BOX</span></div></div><span class="decision">${item.decision}</span></div>
      <div class="metrics">
        <div class="metric"><span>SUMdex価格</span><strong>${yen(item.sumdexPrice)}</strong></div>
        <div class="metric"><span>国内表示最高</span><strong>${item.domestic.highest?yen(item.domestic.highest.price):'―'}</strong></div>
        <div class="metric"><span>国内参考価格</span><strong>${ref?yen(ref.price):'―'}</strong></div>
        <div class="metric"><span>還付見込</span><strong>${yen(item.refund)}</strong></div>
        <div class="metric"><span>実質仕入れ</span><strong>${yen(item.netCost)}</strong></div>
        <div class="metric"><span>想定利益</span><strong>${yen(item.profit)}</strong></div>
      </div>
      <div class="item-actions">
        <label>Discord販売価格<input class="sale-price" data-id="${item.id}" type="number" min="0" max="${item.sumdexPrice}" step="100" value="${item.salePrice}"></label>
        <label class="include"><input class="include-toggle" data-id="${item.id}" type="checkbox" ${item.include?'checked':''}> Discord本文に含める</label>
        <button class="danger-button remove" data-id="${item.id}" type="button">削除</button>
      </div>${ref?`<p class="hint">国内参考：${escapeHtml(ref.site)} ${yen(ref.price)}${ref.guarantee?'（満額保証／減額なし表記）':'（状態による減額リスクあり）'}</p>`:''}${warning?`<p class="warning">⚠️ ${warning}</p>`:''}
    </article>`;
  }).join('');
  buildOutput();saveItems();
}

function buildOutput(){
  const included=items.map(calculate).filter(item=>item.include);
  if(!included.length){$('output').value='';return}
  const groups={good:[],shrink:[],box:[],heavy:[]};
  included.forEach(item=>groups[conditionGroup(item)].push(item));
  const blocks=[];
  const addGroup=(key,title,intro)=>{
    if(!groups[key].length)return;
    blocks.push(`${title}\n\n${intro}`);
    groups[key].forEach(item=>{
      const conditionLines=item.conditions.filter(k=>k!=='clean').map(k=>CONDITION_RULES[k].en);
      if(item.notes.trim())conditionLines.push(item.notes.trim());
      const special=key==='good'&&item.salePrice<item.sumdexPrice
        ?`~~${yen(item.sumdexPrice)}~~ → **${yen(item.salePrice)} / BOX**\n🔥 Discord Special Price`
        :`**${yen(item.salePrice)} / BOX**`;
      blocks.push(`${key==='good'?'🟢':key==='shrink'?'🟡':key==='box'?'🟠':'🔴'} **${item.name}**\n📦 ${item.quantity} BOX\n${special}${conditionLines.length?`\n\nCondition:\n${conditionLines.join('\n')}`:''}`);
    });
  };
  blocks.push('🇯🇵 **JAPAN DAILY STOCK**\n\nToday\'s available stock from Japan.\nSpecial prices for our Discord members.');
  addGroup('good','━━━━━━━━━━━━━━━━━━\n✨ **COLLECTOR / RESELLER**\n━━━━━━━━━━━━━━━━━━','🟢 **GOOD CONDITION**\nRecommended for collectors & resale.\nClean box / No noticeable damage.');
  if(groups.shrink.length||groups.box.length||groups.heavy.length)blocks.push('━━━━━━━━━━━━━━━━━━\n🔥 **OPEN / RESALE DEALS**\n━━━━━━━━━━━━━━━━━━\n\nDiscounted stock based on package condition.');
  addGroup('shrink','🟡 **SHRINK DAMAGE**','Small hole or tear in the shrink wrap.');
  addGroup('box','🟠 **BOX DAMAGE**','Dent, crease, stain or other package damage.');
  addGroup('heavy','🔴 **HEAVY DAMAGE**','Noticeable damage to the box or shrink wrap.\nRecommended mainly for opening.');
  blocks.push('━━━━━━━━━━━━━━━━━━\n📸 **WORRIED ABOUT THE CONDITION?**\n━━━━━━━━━━━━━━━━━━\n\nNo problem! We can send detailed photos or videos of the actual item before purchase.\n\nPlease ask us in your ticket if you would like to check the condition.');
  blocks.push('━━━━━━━━━━━━━━━━━━\n🔎 **LOOKING FOR SOMETHING ELSE?**\n━━━━━━━━━━━━━━━━━━\n\nWe carry more Japanese TCG products than those listed above.\n\nPokémon / ONE PIECE / Other Japanese TCG\n\nIf you\'re looking for a specific product, please open a ticket and let us know:\n• Product name\n• Quantity\n• Target price, if you have one\n\n🎫 **Open a Ticket to Order / Ask**\n📦 Bulk orders welcome\n🌎 Worldwide shipping available\n\n*Stock is limited and available on a first-come, first-served basis.*');
  $('output').value=blocks.join('\n\n');
}

$('productName').addEventListener('change',()=>{const price=getPriceMaster()[$('productName').value];if(price)$('sumdexPrice').value=price});
$('conditionOptions').addEventListener('change',event=>{
  const input=event.target;if(!input.matches('input'))return;
  const all=[...$('conditionOptions').querySelectorAll('input')];
  if(input.value==='clean'&&input.checked)all.filter(x=>x!==input).forEach(x=>x.checked=false);
  else if(input.checked){all.find(x=>x.value==='clean').checked=false;const family=input.value.replace(/Small|Large/,'');all.filter(x=>x!==input&&x.value.replace(/Small|Large/,'')===family).forEach(x=>x.checked=false)}
  if(!all.some(x=>x.checked))all.find(x=>x.value==='clean').checked=true;
});
$('purchaseForm').addEventListener('submit',event=>{
  event.preventDefault();const conditions=selectedConditions();const name=$('productName').value.trim();const sumdexPrice=Number($('sumdexPrice').value);
  savePrice(name,sumdexPrice);
  const newItem={id:uid(),name,sumdexPrice,purchasePrice:Number($('purchasePrice').value),quantity:Number($('quantity').value),expenses:Number($('expenses').value)||0,conditions,notes:$('notes').value.trim()};
  const calculated=calculate(newItem);newItem.salePrice=calculated.suggested;newItem.include=calculated.profit>0&&calculated.profit>=calculated.minProfit;
  items.push(newItem);render();event.target.reset();$('quantity').value=1;$('expenses').value=0;$('conditionOptions').querySelector('[value="clean"]').checked=true;$('productName').focus();
});
$('items').addEventListener('change',event=>{
  const id=event.target.dataset.id;const item=items.find(x=>x.id===id);if(!item)return;
  if(event.target.classList.contains('sale-price')){item.salePrice=Math.min(item.sumdexPrice,Number(event.target.value)||0)}
  if(event.target.classList.contains('include-toggle'))item.include=event.target.checked;
  render();
});
$('items').addEventListener('click',event=>{if(!event.target.classList.contains('remove'))return;items=items.filter(x=>x.id!==event.target.dataset.id);render()});
$('minimumProfit').addEventListener('change',render);$('discountCap').addEventListener('change',render);
$('clearAll').addEventListener('click',()=>{if(items.length&&confirm('登録した商品をすべて削除しますか？')){items=[];render()}});
$('copyButton').addEventListener('click',async()=>{if(!$('output').value)return;await navigator.clipboard.writeText($('output').value);$('copyStatus').textContent='コピーしました。Discordへそのまま貼り付けられます。';setTimeout(()=>$('copyStatus').textContent='',2500)});

loadItems();loadDomesticPrices();
