import {createClient} from '@supabase/supabase-js';
import {SUPABASE_URL,SUPABASE_KEY} from './config.js';
import {CONDITIONS,DEFAULTS,calculate,generate,toggleCondition,yen,nameKey,productNames,domesticForProduct} from './pricing.js';
import {CSV_KEYS,planCatalogImport,validateCatalog} from './catalog.js';
import {parsePriceListCSV,planPriceUpdates} from './price-import.js';
import {matchLiveProduct,matchLiveRowsForPreview,sourceKey} from './live-price.js';
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const note=s=>$('notice').textContent=s;
const uid=()=>crypto.randomUUID();
let client,user,members=[],catalog=[],settings={...DEFAULTS},rows=[],domestic={},versions={},draftId=uid(),dirty=false,catalogDirty=false,settingsDirty=false,domesticDate='未取得';
let savedCatalog='';
let priceImportRows=[];
let liveImport=false;
const PRICE_SOURCES={pokemon:'https://nifty-lady-7a0.notion.site/SUMdex-Price-List-1fb5128517868045b62ad27795b0f0cd',onepiece:'https://nifty-lady-7a0.notion.site/SUMdex-One-Piece-Card-Price-List-2ff51285178680e4a1b3d0d1f8e308f3'};
const blank=()=>({id:uid(),productId:'',cost:'',expenses:0,conditions:['clean'],discounts:{},basis:'sumdex',manualPrice:'',notes:'',include:true});
const clearOutput=()=>{$('output').value='';$('copy').disabled=true;$('charCount').textContent='';};
const changed=()=>{dirty=true;clearOutput();};
const run=fn=>async(...args)=>{try{await fn(...args);}catch(e){note(e.message||String(e));}};
async function getDoc(id){const {data,error}=await client.from('sumdex_documents').select('*').eq('id',id).maybeSingle();if(error)throw error;return data;}
async function saveDoc(id,kind,data){
 const version=versions[id]||0;
 const value={id,kind,data,version:version+1,updated_by:user.id};
 const query=version?client.from('sumdex_documents').update(value).eq('id',id).eq('version',version):client.from('sumdex_documents').insert(value);
 const result=await query.select('version');
 if(result.error||!result.data?.length)throw Error('保存できません。同時編集・権限・接続を確認してください。入力はこの画面に残っています。別タブで最新の下書きを確認してから統合してください。');
 versions[id]=result.data[0].version;note('共有保存しました。');
}
async function loadDomestic(){
 try{
  const res=await fetch('../index.html',{cache:'no-store'});if(!res.ok)throw Error('取得失敗');
  const doc=new DOMParser().parseFromString(await res.text(),'text/html');const result={};let current;
  for(const tr of doc.querySelectorAll('table tr')){
   if(tr.classList.contains('product-row')){const name=tr.querySelector('strong')?.textContent.trim();current=name?result[name]={shops:[]}:null;}
   else if(current){const cells=tr.querySelectorAll('td');if(cells.length<3)continue;
    const price=Number((cells[2].querySelector('.price')?.textContent||cells[2].textContent).match(/[\d,]+/)?.[0].replaceAll(',',''));
    if(price>0)current.shops.push({site:(cells[0].childNodes[0]?.textContent||cells[0].textContent).trim(),price,guarantee:cells[0].querySelector('.condition-badge')?.textContent.trim()||'保証表示なし'});
   }
  }
  if(!Object.keys(result).length)throw Error('商品データがありません');
  domestic=result;domesticDate=doc.querySelector('.updated')?.textContent.trim()||'更新日時不明';
  $('sourceStatus').textContent=`国内価格 ${Object.keys(result).length}商品｜${domesticDate}｜保証の状態適用は別途確認`;
 }catch(e){domestic={};$('sourceStatus').textContent='国内価格の取得に失敗。国内価格優先の行は掲載できません。';}
 clearOutput();renderRows();
}
function renderRows(){
 $('rows').innerHTML=rows.map((row,i)=>{
  const p=catalog.find(p=>p.id===row.productId),d=domesticForProduct(domestic,p),c=calculate(row,p,settings,d);
  const priceMissing=Boolean(p)&&(!Number.isFinite(p.price)||p.price<=0);
  const checkedAt=Date.parse(p?.checkedAt||'');
  const priceNeedsCheck=p&&!priceMissing&&(!Number.isFinite(checkedAt)||Date.now()-checkedAt>86400000||checkedAt>Date.now()+60000);
  const priceLabel=priceMissing?'価格未入力':priceNeedsCheck?`${yen(p.price)}（要再確認）`:p?.price?yen(p.price):'商品未選択';
  return `<article class="item ${c.profit<0?'loss':''}" data-row="${row.id}"><div class="item-head"><h3>商品 ${i+1}</h3><div class="toolbar"><button data-action="duplicate">複製</button><button data-action="remove">行を削除</button><label class="include"><input data-field="include" type="checkbox" ${row.include?'checked':''}>掲載する</label></div></div>
  <div class="grid"><label>商品名を日本語・英語で検索<input data-search="product" list="productNames" placeholder="日本語名・英語名・型番"></label><label>商品<select data-field="productId"><option value="">選択してください</option>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===row.productId?'selected':''}>${esc(p.ja)} / ${esc(p.en)} [${esc(p.code)}]</option>`).join('')}</select></label>
  <label>税込仕入れ値（円 / BOX）<input data-field="cost" type="number" min="1" value="${esc(row.cost)}"></label><label>送料・決済など負担費用（円 / BOX）<input data-field="expenses" type="number" min="0" value="${esc(row.expenses)}"></label>
  <label>優先する価格<select data-field="basis"><option value="sumdex" ${row.basis==='sumdex'?'selected':''}>SUMdexから割引</option><option value="domestic" ${row.basis==='domestic'?'selected':''}>国内表示最高値を下回らない</option></select></label></div>
  <div class="conditions">${Object.entries(CONDITIONS).map(([k,v])=>`<label><input type="checkbox" data-condition="${k}" ${row.conditions.includes(k)?'checked':''}>${v[0]}</label>`).join('')}</div>
  <details><summary>この行の割引を調整</summary><div class="grid">${['clean',...row.conditions.filter(k=>k!=='clean')].map(k=>`<label>${k==='clean'?'基本割引':CONDITIONS[k][0]+' 追加割引'}<input data-discount="${k}" type="number" min="0" value="${row.discounts[k]??settings[k]}"></label>`).join('')}</div><button data-action="reset">行の調整をリセット</button></details>
  <div class="grid"><label>販売価格を手動調整（空欄なら自動）<input data-field="manualPrice" type="number" min="1" value="${esc(row.manualPrice)}" placeholder="${c.sale??''}"></label><label>状態の補足（英語・投稿に表示）<input data-field="notes" value="${esc(row.notes)}" placeholder="例：Dent on the top right corner."></label></div>
  <div class="metrics">${[['SUMdex',priceLabel],['Discord',c.sale!=null?yen(c.sale):'―'],['還付見込',yen(c.refund)],['還付込み利益',c.profit!=null?yen(c.profit):'―'],['国内表示最高',c.highest?yen(c.highest):'―']].map(([a,b])=>`<div><span>${a}</span><strong>${b}</strong></div>`).join('')}</div>
  ${p&&(priceMissing||priceNeedsCheck)?`<p class="warning">${priceMissing?'商品名は登録済みですが、SUMdex価格はまだ入力されていません。':'SUMdex価格の確認日時がありません、または24時間以上経過しました。'} <button data-price-product="${esc(p.id)}">この商品の価格を登録・確認</button></p>`:''}
  <p class="muted">還付見込＝税込仕入れ値 ÷ 11。${c.profit===0?'利益なし。':''}国内価格は買取確約ではありません。</p>
  ${c.highest&&c.sale<c.highest?'<p class="warning">国内販売も比較してください。ダメージ減額・保証条件の確認後に判断します。</p>':''}
  ${c.errors.length?`<p class="warning">${c.errors.map(esc).join('<br>')}</p>`:''}
  ${d?`<details><summary>店舗ごとの表示価格・保証表示</summary>${d.shops.map(s=>`<p>${esc(s.site)}：${yen(s.price)} ／ ${esc(s.guarantee)} ／ この状態への適用：要確認</p>`).join('')}</details>`:''}</article>`;
 }).join('');
}
function renderCatalog(){
 $('productNames').innerHTML=catalog.flatMap(p=>[...productNames(p),p.code].map(name=>`<option value="${esc(name)} [${esc(p.code)}]"></option>`)).join('');
 const query=nameKey($('catalogSearch').value),visible=catalog.filter(p=>!query||[...productNames(p),p.code].some(n=>nameKey(n).includes(query)));
 $('catalogSummary').textContent=`登録 ${catalog.length}件 ／ 価格確認済 ${catalog.filter(p=>p.checkedAt&&p.price&&p.sourceUrl).length}件 ／ 表示 ${visible.length}件${catalogDirty?' ／ 未保存の変更あり':''}`;
 $('products').innerHTML=visible.map(p=>`<article class="product grid" data-product="${esc(p.id)}"><p class="catalog-title">${esc(p.ja)} ／ ${esc(p.en||'英語名未入力')} <span class="muted">[${esc(p.code||'型番未入力')}]</span></p>${[['ja','国内買取の表記（日本語など）'],['en','投稿に使う英語名（他サイトの表記でも可）'],['code','型番（大小文字どちらでも可）'],['domesticNames','国内買取の別表記（複数は | で区切る）'],['price','SUMdex価格（円・後から入力可）'],['sourceUrl','SUMdex価格表URL（後から入力可）']].map(([k,label])=>`<label>${label}<input data-field="${k}" ${k==='price'?'type="number" min="1"':''} value="${esc(p[k])}"></label>`).join('')}<p class="muted">${p.checkedAt&&p.price&&p.sourceUrl?'価格確認済：'+esc(new Date(p.checkedAt).toLocaleString('ja-JP')):'商品名の紐づけを保存できます。販売前にSUMdex価格と価格表URLを確認してください。'}${p.notionRowId?' ／ Notion商品と紐づけ済み':''}${/^https:\/\//.test(p.sourceUrl)?` ／ <a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">この商品の価格表を開く</a>`:''}</p><div class="toolbar"><button data-check="${esc(p.id)}">価格を確認済みにする</button><button data-delete="${esc(p.id)}">この商品を削除</button></div></article>`).join('');
}
async function getLiveLists(sources){const {data,error}=await client.functions.invoke('sumdex-notion-prices',{body:{sources}});if(error||!Array.isArray(data?.lists))throw Error('Notion価格表を取得できません。時間を置いて再試行するか、CSVを取り込んでください。');return data.lists;}
function renderPriceImport(){
 $('priceImportSummary').textContent=priceImportRows.length?`CSV ${priceImportRows.length}行 ／ 照合 ${priceImportRows.filter(r=>r.productId).length}行 ／ 未照合 ${priceImportRows.filter(r=>!r.productId).length}行。除外した行は価格を更新しません。`:'';
 $('priceImportPreview').innerHTML=priceImportRows.map((row,i)=>`<tr><td>${row.line}</td><td>${esc(row.sourceName||row.sourceCode)}</td><td>${row.price?yen(row.price):'読み取れません'}</td><td><select data-price-row="${i}" aria-label="CSV ${row.line}行目の対応商品"><option value="">除外・未照合</option>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===row.productId?'selected':''}>${esc(p.ja)} / ${esc(p.en)} [${esc(p.code)}]</option>`).join('')}</select></td><td>${esc(row.reason)}</td></tr>`).join('');
 $('applyPriceList').disabled=!priceImportRows.some(r=>r.productId);
}
function matchProduct(query){const key=nameKey(query);if(!key)return null;const hits=catalog.filter(p=>[...productNames(p),p.code,...productNames(p).map(n=>`${n} [${p.code}]`)].some(n=>nameKey(n)===key));return hits.length===1?hits[0]:null;}
function renderSettings(){ $('discounts').innerHTML=Object.entries(CONDITIONS).map(([k,v])=>`<label>${k==='clean'?'綺麗な商品の基本割引':v[0]+'の追加割引'}（円）<input data-setting="${k}" type="number" min="0" value="${settings[k]}"></label>`).join(''); }
async function loadMembers(){
 const {data,error}=await client.from('sumdex_members').select('*');if(error)throw error;members=data;
 const admin=members.find(m=>m.email===user.email?.toLowerCase())?.role==='admin';$('membersPanel').hidden=!admin;
 $('members').innerHTML=members.map(m=>`<p>${esc(m.email)} · ${esc(m.role)} · ${m.active?'有効':'停止'} ${admin&&m.email!==user.email?.toLowerCase()?`<button data-member="${esc(m.email)}" data-active="${!m.active}">${m.active?'利用停止':'再開'}</button>`:''}</p>`).join('');
}
async function listDrafts(){const {data,error}=await client.from('sumdex_documents').select('id,data,updated_at').eq('kind','draft').order('updated_at',{ascending:false});if(error)throw error;$('draftList').innerHTML='<option value="">保存した下書き</option>'+data.map(d=>`<option value="${esc(d.id)}">${esc(d.data.title||'無題')} · ${esc(new Date(d.updated_at).toLocaleString('ja-JP'))}</option>`).join('');}
async function start(){
 const {data,error}=await client.auth.getUser();if(error||!data.user)return;user=data.user;
 await loadMembers();if(!members.some(m=>m.email===user.email?.toLowerCase()&&m.active))throw Error('このアカウントは利用登録されていません。管理者に連絡してください。');
 const [c,s]=await Promise.all([getDoc('catalog'),getDoc('settings')]);catalog=c?.data.products||[];settings={...DEFAULTS,...s?.data};versions.catalog=c?.version||0;versions.settings=s?.version||0;savedCatalog=JSON.stringify(catalog);
 rows=[blank()];$('account').textContent=user.email;$('logout').hidden=false;$('login').hidden=true;$('workspace').hidden=false;
 renderCatalog();$('catalogSaveStatus').textContent=`共有商品表を読み込みました：${catalog.length}件`;renderSettings();renderRows();await Promise.all([loadDomestic(),listDrafts()]);
 note('共有ワークスペースに接続しました。変更後は「共有保存」を押してください。');
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==b.dataset.page);document.querySelectorAll('[data-page]').forEach(p=>p.classList.toggle('active',p===b));});
$('addRow').onclick=()=>{rows.push(blank());changed();renderRows();};
$('rows').oninput=e=>{const row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row),t=e.target;if(!row||t.type==='checkbox')return;if(t.dataset.field){row[t.dataset.field]=t.value;changed();}else if(t.dataset.discount&&t.value!==''&&Number.isFinite(Number(t.value))&&Number(t.value)>=0){row.discounts[t.dataset.discount]=Number(t.value);changed();}};
$('rows').onchange=e=>{const row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row)return;const t=e.target;
 if(t.dataset.search){const product=matchProduct(t.value);if(!product){note('商品名が未登録、または複数の商品と一致します。商品表で日本語名・英語名・型番を確認してください。');return;}row.productId=product.id;changed();renderRows();return;}
 if(t.dataset.condition)row.conditions=toggleCondition(row.conditions,t.dataset.condition,t.checked);
 else if(t.dataset.discount){const n=Number(t.value);if(!Number.isFinite(n)||n<0){note('割引は0以上の数値にしてください');renderRows();return;}row.discounts[t.dataset.discount]=n;}
 else if(t.dataset.field)row[t.dataset.field]=t.type==='checkbox'?t.checked:t.value;
 changed();renderRows();};
$('rows').onclick=e=>{const priceTarget=e.target.closest('[data-price-product]');if(priceTarget){const p=catalog.find(x=>x.id===priceTarget.dataset.priceProduct);if(!p)return;$('catalogSearch').value=p.ja;renderCatalog();document.querySelector('[data-page="catalog"]').click();$('products').firstElementChild?.scrollIntoView({behavior:'smooth',block:'start'});$('products').querySelector('[data-field="price"]')?.focus({preventScroll:true});note(`「${p.ja}」のSUMdex価格と価格表URLを入力し、「価格を確認済みにする」→「商品表を共有保存」を押してください。`);return;}const action=e.target.dataset.action,row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row||!action)return;
 if(action==='duplicate')rows.splice(rows.indexOf(row)+1,0,{...structuredClone(row),id:uid()});if(action==='remove')rows=rows.filter(r=>r!==row);if(action==='reset')row.discounts={};changed();renderRows();};
$('saveDraft').onclick=run(async()=>{await saveDoc(draftId,'draft',{title:$('draftTitle').value,rows});dirty=false;await listDrafts();});
$('loadDraft').onclick=run(async()=>{if(!$('draftList').value)return;if(dirty&&!confirm('未保存の変更を破棄して開きますか？'))return;const d=await getDoc($('draftList').value);if(!d)throw Error('下書きが見つかりません');draftId=d.id;versions[d.id]=d.version;rows=d.data.rows;$('draftTitle').value=d.data.title;dirty=false;clearOutput();renderRows();});
$('newDraft').onclick=()=>{if(dirty&&!confirm('未保存の変更を破棄しますか？'))return;draftId=uid();rows=[blank()];$('draftTitle').value='';dirty=false;clearOutput();renderRows();};
$('draftTitle').oninput=changed;
$('refreshPrices').onclick=run(loadDomestic);
$('catalogSearch').oninput=renderCatalog;
$('priceSource').onchange=()=>{priceImportRows=[];liveImport=false;renderPriceImport();note('参照する価格表を変更しました。価格表を取得し直してください。');};
$('fetchNotion').onclick=run(async()=>{priceImportRows=[];renderPriceImport();const [list]=await getLiveLists([$('priceSource').value]);priceImportRows=matchLiveRowsForPreview(list,catalog);liveImport=true;renderPriceImport();note(`Notionから${list.rows.length}商品の価格を取得しました。対応と価格を確認して反映してください。`);});
$('priceCSV').onchange=run(async e=>{const file=e.target.files[0];if(!file)return;priceImportRows=[];liveImport=false;renderPriceImport();try{priceImportRows=parsePriceListCSV(await file.text(),catalog);renderPriceImport();note('価格表CSVを読み込みました。商品との対応と価格を確認し、問題なければ「価格を商品表に反映」を押してください。');}finally{e.target.value='';}});
$('priceImportPreview').onchange=e=>{const row=priceImportRows[Number(e.target.dataset.priceRow)];if(!row)return;row.productId=e.target.value;row.reason=row.productId?'手動で対応を指定':'除外・未照合';renderPriceImport();};
$('applyPriceList').onclick=run(async()=>{const updates=planPriceUpdates(priceImportRows,catalog);if(!updates.size)throw Error('反映できる商品がありません');if(liveImport){for(const id of updates.keys())if(priceImportRows.filter(row=>row.productId===id).length>1)throw Error('同じ商品にNotionの複数行が選ばれています。1行だけ残してください。');}const sourceUrl=PRICE_SOURCES[$('priceSource').value];if(!sourceUrl)throw Error('価格表を選択してください');if(!confirm(`${updates.size}商品のSUMdex価格と参照先を画面に反映します。商品との対応と金額を確認しましたか？`))return;const checkedAt=new Date().toISOString();catalog=catalog.map(p=>updates.has(p.id)?{...p,price:updates.get(p.id).price,sourceUrl,checkedAt,notionRowId:liveImport?priceImportRows.find(row=>row.productId===p.id)?.notionRowId||'':p.sourceUrl===sourceUrl?p.notionRowId||'':''}:p);catalogDirty=true;priceImportRows=[];liveImport=false;renderPriceImport();renderCatalog();renderRows();clearOutput();$('catalogSaveStatus').textContent=`${updates.size}商品の価格を反映済み・未保存。「商品表を共有保存」を押してください。`;note(`${updates.size}商品の価格を画面に反映しました。「商品表を共有保存」を押すと別のPCでも使えます。`);});
$('addProduct').onclick=()=>{$('catalogSearch').value='';catalog.push({id:uid(),ja:'',en:'',code:'',domesticNames:'',price:'',sourceUrl:'',checkedAt:''});catalogDirty=true;clearOutput();renderCatalog();$('products').lastElementChild?.scrollIntoView({behavior:'smooth',block:'center'});};
$('products').onchange=e=>{const p=catalog.find(p=>p.id===e.target.closest('[data-product]')?.dataset.product);if(!p||!e.target.dataset.field)return;const k=e.target.dataset.field;const next=k==='price'?Number(e.target.value):e.target.value.trim();if(p[k]!==next){p[k]=next;if(k==='price'||k==='sourceUrl')p.checkedAt='';if(k==='sourceUrl'||k==='en'||k==='code')p.notionRowId='';catalogDirty=true;clearOutput();renderRows();renderCatalog();}};
$('products').onclick=e=>{const target=e.target.closest('[data-check],[data-delete]');if(!target)return;const p=catalog.find(p=>p.id===(target.dataset.check||target.dataset.delete));if(!p)return;if(target.dataset.delete){if(!confirm(`「${p.ja||'未入力の商品'}」を商品表から削除しますか？共有保存で確定します。`))return;catalog=catalog.filter(x=>x!==p);catalogDirty=true;clearOutput();renderRows();renderCatalog();return;}if(!p.sourceUrl||!Number.isFinite(Number(p.price))||Number(p.price)<=0){note('SUMdex価格と価格表URLを入力してから確認してください');return;}p.checkedAt=new Date().toISOString();catalogDirty=true;renderCatalog();note('確認日時を記録しました。「商品表を共有保存」で確定してください。');};
$('saveCatalog').onclick=run(async()=>{validateCatalog(catalog);await saveDoc('catalog','catalog',{products:catalog});catalogDirty=false;savedCatalog=JSON.stringify(catalog);renderCatalog();renderRows();$('catalogSaveStatus').textContent=`共有保存済み：${catalog.length}件（${new Date().toLocaleString('ja-JP')}）`;note(`商品表 ${catalog.length}件を共有保存しました。別のPCで開いても反映されます。`);});
$('reloadCatalog').onclick=run(async()=>{if(catalogDirty&&!confirm('まだ共有保存していない商品表の変更を破棄して再読込しますか？'))return;const latest=await getDoc('catalog');catalog=latest?.data.products||[];versions.catalog=latest?.version||0;savedCatalog=JSON.stringify(catalog);catalogDirty=false;priceImportRows=[];renderPriceImport();renderCatalog();renderRows();clearOutput();$('catalogSaveStatus').textContent=`共有商品表を再読込しました：${catalog.length}件`;note('最新の共有商品表を読み込みました。');});
$('discounts').onchange=e=>{const n=Number(e.target.value);if(!Number.isFinite(n)||n<0){renderSettings();return;}settings[e.target.dataset.setting]=n;settingsDirty=true;clearOutput();renderRows();};
$('saveSettings').onclick=run(async()=>{await saveDoc('settings','settings',settings);settingsDirty=false;});
async function verifyPrices({forCopy=false}={}){
 if(catalogDirty||settingsDirty)throw Error('商品表・割引設定の変更を共有保存してから生成してください');
 const latestSettings=await getDoc('settings');if((latestSettings?.version||0)!==(versions.settings||0)){settings={...DEFAULTS,...latestSettings?.data};versions.settings=latestSettings?.version||0;renderSettings();renderRows();clearOutput();throw Error('共有の割引設定が更新されました。新しい割引と価格を確認し、もう一度生成してください');}
 const latest=await getDoc('catalog');if(JSON.stringify(latest?.data.products||[])!==savedCatalog){catalog=latest?.data.products||[];versions.catalog=latest?.version||0;savedCatalog=JSON.stringify(catalog);renderCatalog();renderRows();clearOutput();throw Error('共有の商品表が更新されました。新しい価格を確認し、もう一度生成してください');}
 const selected=[...new Set(rows.filter(r=>r.include).map(r=>r.productId))].map(id=>catalog.find(p=>p.id===id));
 if(selected.some(p=>!p))throw Error('掲載する商品を選択してください');
 if(!selected.length)return [];
 const sources=[...new Set(selected.flatMap(p=>sourceKey(p.sourceUrl)?[sourceKey(p.sourceUrl)]:['pokemon','onepiece']))];
 const lists=await getLiveLists(sources),updates=[];
 for(const p of selected){
  const {row,list}=matchLiveProduct(p,lists);
  if(!Number.isSafeInteger(row.price)||row.price<=0)throw Error(`「${p.ja}」のNotion価格が不正です`);
  if(p.price!==row.price||p.sourceUrl!==list.url||p.notionRowId!==row.id||!p.checkedAt||Date.now()-Date.parse(p.checkedAt)>86400000)updates.push({id:p.id,old:p.price,price:row.price,sourceUrl:list.url,notionRowId:row.id});
 }
 if(updates.length){
  const checkedAt=new Date().toISOString();const next=catalog.map(p=>{const update=updates.find(x=>x.id===p.id);return update?{...p,price:update.price,sourceUrl:update.sourceUrl,notionRowId:update.notionRowId,checkedAt}:p;});
  validateCatalog(next);await saveDoc('catalog','catalog',{products:next});catalog=next;savedCatalog=JSON.stringify(catalog);renderCatalog();renderRows();
  const priceChanges=updates.filter(x=>x.old!==x.price);
  if(forCopy&&priceChanges.length){clearOutput();throw Error(`SUMdex価格が変更されました（${priceChanges.map(x=>`${yen(x.old||0)}→${yen(x.price)}`).join('、')}）。新しい価格を確認して本文を再生成してください。`);}
 }
 return updates.filter(x=>x.old!==x.price);
}
$('generate').onclick=run(async()=>{clearOutput();const changes=await verifyPrices();await loadDomestic();const out=generate(rows,catalog,settings,domestic);$('outputErrors').textContent=out.errors.join(' ／ ');if(out.errors.length)return;$('output').value=out.text;$('copy').disabled=!out.text;$('charCount').textContent=`${out.text.length.toLocaleString()}文字`;
 note(changes.length?`Notionの価格変更を反映しました：${changes.map(x=>`${yen(x.old||0)}→${yen(x.price)}`).join('、')}。本文の価格を確認してください。`:'Notionの最新価格と共有商品表の一致を確認しました。');});
$('copy').onclick=run(async()=>{await verifyPrices({forCopy:true});if(!$('output').value)return;await navigator.clipboard.writeText($('output').value);note('コピーしました。Discordに貼り付けてください。');});
function downloadCatalogCSV(products,filename){const csv=[CSV_KEYS,...products.map(p=>CSV_KEYS.map(k=>p[k]))].map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('exportCSV').onclick=()=>downloadCatalogCSV(catalog,'sumdex-products.csv');
$('exportDomesticCSV').onclick=()=>{const unmapped=Object.keys(domestic).filter(name=>!catalog.some(p=>[p.ja,...String(p.domesticNames||'').split('|')].some(s=>nameKey(s)===nameKey(name))));if(!unmapped.length){note('国内価格データに未登録の商品名がありません。国内価格の取得状況を確認してください。');return;}downloadCatalogCSV(unmapped.map(ja=>({ja})),'sumdex-domestic-unmapped.csv');note(`${unmapped.length}件の国内商品名をCSVに書き出しました。販売する商品の英語名・型番・価格を確認して入力してください。`);};
$('importCSV').onchange=run(async e=>{const file=e.target.files[0];if(!file)return;const {products,added,updated,skipped}=planCatalogImport(await file.text(),catalog,uid);if(!added&&!updated){note(`登録対象は0件です。未入力の${skipped}行は取り込みません。`);e.target.value='';return;}if(!confirm(`新規 ${added}件・更新 ${updated}件を画面に取り込みます。未入力の${skipped}行は飛ばします。この後「商品表を共有保存」を押すと別のPCにも反映されます。続けますか？`))return;catalog=products;catalogDirty=true;$('catalogSaveStatus').textContent=`取り込み済み：新規 ${added}件・更新 ${updated}件。まだ共有保存されていません。`;clearOutput();renderCatalog();renderRows();note('商品名を確認し、「商品表を共有保存」を押してください。価格は販売する商品から後で登録できます。');e.target.value='';});
$('addMember').onclick=run(async()=>{const email=$('memberEmail').value.trim().toLowerCase();if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))throw Error('メールアドレスを確認してください');const {error}=await client.from('sumdex_members').insert({email,role:'editor',active:true});if(error)throw error;await loadMembers();note('利用者を登録しました。Google側がテスト中の場合はテストユーザーにも追加してください。');});
$('members').onclick=run(async e=>{if(!e.target.dataset.member)return;const {error}=await client.from('sumdex_members').update({active:e.target.dataset.active==='true'}).eq('email',e.target.dataset.member);if(error)throw error;await loadMembers();});
window.addEventListener('beforeunload',e=>{if(dirty||catalogDirty||settingsDirty){e.preventDefault();e.returnValue='';}});
if(!SUPABASE_KEY){$('signIn').disabled=true;note('共有データベースの接続設定中です。まだ運用開始できません。');}
else{
 client=createClient(SUPABASE_URL,SUPABASE_KEY,{auth:{flowType:'pkce'}});
 $('signIn').onclick=run(async()=>{const {error}=await client.auth.signInWithOAuth({provider:'google',options:{redirectTo:new URL('./',location.href).href}});if(error)throw error;});
 $('logout').onclick=run(async()=>{if((dirty||catalogDirty||settingsDirty)&&!confirm('未保存の変更があります。ログアウトしますか？'))return;await client.auth.signOut();dirty=catalogDirty=settingsDirty=false;location.reload();});
 client.auth.onAuthStateChange(event=>{if(event==='SIGNED_OUT'){$('workspace').hidden=true;$('login').hidden=false;rows=[];catalog=[];clearOutput();}});
 run(start)();
}
