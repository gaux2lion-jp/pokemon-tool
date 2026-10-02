import {createClient} from '@supabase/supabase-js';
import {SUPABASE_URL,SUPABASE_KEY} from './config.js';
import {CONDITIONS,DEFAULTS,calculate,recommendPriceBasis,generate,toggleCondition,conditionKey,normalizeConditionRow,yen,nameKey,productNames,domesticForProduct} from './pricing.js';
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
let rowPriceStatus={};
let priceRefreshQueue=Promise.resolve();
const PRICE_SOURCES={pokemon:'https://nifty-lady-7a0.notion.site/SUMdex-Price-List-1fb5128517868045b62ad27795b0f0cd',onepiece:'https://nifty-lady-7a0.notion.site/SUMdex-One-Piece-Card-Price-List-2ff51285178680e4a1b3d0d1f8e308f3'};
const blank=()=>({id:uid(),productId:'',cost:'',expenses:0,conditions:['sa'],discounts:{},basis:'auto',manualPrice:'',notes:'',allowLoss:false,include:true});
const clearOutput=()=>{$('output').value='';$('copy').disabled=true;$('charCount').textContent='';$('outputErrors').textContent='';$('copyHint').textContent='まず価格を確認して本文を作ってください。';};
const changed=()=>{dirty=true;clearOutput();$('copyHint').textContent='入力を変更したため、本文を作り直してください。';updateFlow();};
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
  const recommendation=recommendPriceBasis(row,p,settings,d),priceStatus=rowPriceStatus[row.id]?.productId===row.productId?rowPriceStatus[row.id]:null;
  const priceMissing=Boolean(p)&&(!Number.isFinite(p.price)||p.price<=0);
  const checkedAt=Date.parse(p?.checkedAt||'');
  const priceNeedsCheck=p&&!priceMissing&&(!Number.isFinite(checkedAt)||Date.now()-checkedAt>86400000||checkedAt>Date.now()+60000);
  const priceLabel=priceMissing?'価格未入力':priceNeedsCheck?`${yen(p.price)}（要再確認）`:p?.price?yen(p.price):'商品未選択';
  return `<article class="item ${c.profit<0?'loss':''}" data-row="${row.id}"><div class="item-head"><h3>商品 ${i+1} <span class="row-state">${row.include?'投稿に含める':'投稿から除外'}</span></h3><div class="toolbar"><label class="include"><input data-field="include" type="checkbox" ${row.include?'checked':''}>投稿に含める</label><button data-action="duplicate">この行を複製</button><button data-action="remove" ${rows.length===1?'disabled title="最初の1行は残します"':''}>削除</button></div></div>
  <div class="entry-grid"><div class="product-picker"><label>① 商品を検索（日本語・英語・型番）<input data-search="product" type="search" autocomplete="off" placeholder="例：ニンジャスピナー / Ninja Spinner / m4"></label><div class="search-results" data-results hidden></div><p class="selected-product">${p?`選択中：<strong>${esc(p.ja)} / ${esc(p.en)}${String(p.code??" ").trim()?` [${esc(p.code)}]`:""}</strong>`:'未選択：検索結果の商品を押してください'}</p><details><summary>一覧から選ぶ・検索しても見つからないとき</summary><label>登録済み商品<select data-field="productId"><option value="">選択してください</option>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===row.productId?'selected':''}>${esc(p.ja)} / ${esc(p.en)}${String(p.code??" ").trim()?` [${esc(p.code)}]`:""}</option>`).join('')}</select></label><p class="muted">商品がない場合は上の「商品名・価格表」から追加します。</p></details></div>
  <label>② 税込仕入れ値（円 / BOX）<input data-field="cost" type="number" min="1" inputmode="numeric" value="${esc(row.cost)}" placeholder="例：7000"></label></div>
  <p class="field-title">③ コンディションと割引額を決める</p><div class="condition-entry"><div class="conditions">${Object.entries(CONDITIONS).map(([k,v])=>`<label><input type="radio" name="condition-${row.id}" data-condition="${k}" ${conditionKey(row)===k?'checked':''}>${v[0]}</label>`).join('')}</div><label class="row-discount">この商品の割引額（円）<input data-discount="${conditionKey(row)}" type="number" min="0" inputmode="numeric" value="${row.discounts[conditionKey(row)]??settings[conditionKey(row)]}" aria-label="${CONDITIONS[conditionKey(row)][0]}の割引額"></label></div><p class="muted">共有設定の金額が入ります。この商品だけ変える場合は、ここで上書きしてください。</p>
  <section class="price-guide ${recommendation.status}"><div class="price-guide-head"><div><p class="field-title">④ 価格を比較して決定</p><p class="muted">商品選択時にSUMdex価格を確認し、国内最高表示額と比較します。</p></div>${p?`<button type="button" data-action="refresh-price" ${priceStatus?.state==='loading'?'disabled':''}>${priceStatus?.state==='loading'?'価格を確認中…':'価格を今確認'}</button>`:''}</div>
  ${!p?'<p>商品を選ぶと価格を表示します。</p>':`<div class="price-compare"><div><span>SUMdex価格</span><strong>${priceLabel}</strong><small>Discord価格の上限</small></div><div><span>国内最高表示額</span><strong>${c.highest?yen(c.highest):'未確認'}</strong><small>状態減額前・満額保証ではありません</small></div><div><span>自動計算したDiscord価格</span><strong>${c.sale!=null?yen(c.sale):'計算待ち'}</strong><small>状態割引・赤字判定を反映</small></div></div>
  <div class="recommendation"><strong data-recommendation-title>自動おすすめ：${esc(recommendation.title)}</strong><p data-recommendation-reason>${esc(recommendation.reason)}</p></div>
  ${priceStatus?.state==='loading'?'<p class="price-status">NotionのSUMdex価格を確認しています…</p>':''}${priceStatus?.state==='success'?`<p class="price-status success">最新価格を確認しました：${esc(priceStatus.message)}</p>`:''}${priceStatus?.state==='error'?`<p class="price-status error">${esc(priceStatus.message)} <button type="button" data-price-product="${esc(p.id)}">商品名・型番の紐づけを確認</button></p>`:''}
  <label class="basis-select">価格設定<select data-field="basis"><option value="auto" ${row.basis==='auto'?'selected':''}>おすすめを自動選択</option><option value="sumdex" ${row.basis==='sumdex'?'selected':''}>SUMdex価格から状態別に割引</option><option value="domestic" ${row.basis==='domestic'?'selected':''}>国内最高表示額を下回らない</option></select></label>`}</section>
  <details class="advanced"><summary>費用や説明を調整したいときだけ開く</summary><div class="grid"><label>送料・決済など負担費用（円 / BOX）<input data-field="expenses" type="number" min="0" value="${esc(row.expenses)}"></label><label>販売価格を手動調整（空欄なら自動）<input data-field="manualPrice" type="number" min="1" value="${esc(row.manualPrice)}" placeholder="${c.sale??''}"></label><label>状態の補足（英語・投稿に表示）<input data-field="notes" value="${esc(row.notes)}" placeholder="例：Dent on the top right corner."></label></div><button data-action="reset">この商品の割引額を共有設定に戻す</button></details>
  <div class="metrics">${[['SUMdex',priceLabel],['Discord',c.sale!=null?yen(c.sale):'―'],['還付見込',yen(c.refund)],['還付込み利益',c.profit!=null?yen(c.profit):'―'],['国内表示最高',c.highest?yen(c.highest):'―']].map(([a,b])=>`<div><span>${a}</span><strong>${b}</strong></div>`).join('')}</div>
  ${c.profit<0?`<label class="loss-choice"><input data-field="allowLoss" type="checkbox" ${row.allowLoss?'checked':''}><span><strong>赤字 ${yen(Math.abs(c.profit))}を確認し、それでも掲載する</strong><small>チェックを入れた行だけ、赤字でも投稿文を作成できます。</small></span></label>`:''}
  <p class="warning" data-live-warning>${row.include&&p&&row.cost?c.errors.filter(error=>!(priceMissing&&error.includes('SUMdex価格が未入力'))).map(esc).join(' ／ '):''}</p>
  ${p&&(priceMissing||priceNeedsCheck)&&priceStatus?.state!=='loading'?`<p class="warning">${priceMissing?'SUMdex価格はまだ未登録です。':'前回の価格確認から24時間以上経過しています。生成時にNotionの価格を再確認します。'} ${priceMissing?`<button data-price-product="${esc(p.id)}">商品情報を確認</button>`:''}</p>`:''}
  <p class="muted">還付見込＝税込仕入れ値 ÷ 11。${c.profit===0?'利益なし。':''}国内価格は買取確約ではありません。</p>
  ${c.highest&&c.sale<c.highest?'<p class="warning">国内販売も比較してください。ダメージ減額・保証条件の確認後に判断します。</p>':''}
  ${d?`<details><summary>店舗ごとの表示価格・保証表示</summary>${d.shops.map(s=>`<p>${esc(s.site)}：${yen(s.price)} ／ ${esc(s.guarantee)} ／ この状態への適用：要確認</p>`).join('')}</details>`:''}</article>`;
 }).join('');
 updateFlow();
}
function updateFlow(){
 const included=rows.filter(r=>r.include),missing=included.filter(r=>!r.productId||!Number(r.cost));
 $('flowStatus').textContent=!included.length?'投稿する商品を1行以上選んでください。':missing.length?`入力待ち：${missing.length}行の商品または仕入れ値を入力してください。`:`${included.length}行が入力済みです。価格を確認して本文を作ってください。`;
 $('draftState').textContent=dirty?'下書き：未保存の変更あり（このまま本文生成できます）':'下書き：保存済み、または未作成';
}
function showSearchResults(input){
 const box=input.closest('[data-row]'),results=box.querySelector('[data-results]'),key=nameKey(input.value);
 if(!key){results.hidden=true;results.innerHTML='';return;}
 const matches=catalog.filter(p=>[...productNames(p),p.code].some(n=>nameKey(n).includes(key)));
 results.hidden=false;
 results.innerHTML=matches.length?`<p>${matches.length}件見つかりました。商品名を押して確定してください。</p>${matches.slice(0,8).map(p=>`<button type="button" data-pick="${esc(p.id)}">${esc(p.ja)} / ${esc(p.en)}${String(p.code??" ").trim()?` [${esc(p.code)}]`:""}</button>`).join('')}${matches.length>8?'<p>候補が多い場合は、続けて文字を入力してください。</p>':''}`:'<p>該当なし。商品名・価格表から商品を追加できます。</p>';
}
function rerenderRow(row){const old=$('rows').querySelector(`[data-row="${row.id}"]`),advanced=old?.querySelector('.advanced')?.open;renderRows();const current=$('rows').querySelector(`[data-row="${row.id}"]`);if(advanced)current.querySelector('.advanced').open=true;}
function refreshRowPreview(row){const card=$('rows').querySelector(`[data-row="${row.id}"]`),product=catalog.find(p=>p.id===row.productId),matchedDomestic=domesticForProduct(domestic,product),c=calculate(row,product,settings,matchedDomestic),recommendation=recommendPriceBasis(row,product,settings,matchedDomestic);if(!card)return;const values=card.querySelectorAll('.metrics strong');values[1].textContent=c.sale!=null?yen(c.sale):'―';values[2].textContent=yen(c.refund);values[3].textContent=c.profit!=null?yen(c.profit):'―';values[4].textContent=c.highest?yen(c.highest):'―';const compared=card.querySelectorAll('.price-compare strong');if(compared.length===3)compared[2].textContent=c.sale!=null?yen(c.sale):'計算待ち';card.querySelector('[data-recommendation-title]')?.replaceChildren(`自動おすすめ：${recommendation.title}`);card.querySelector('[data-recommendation-reason]')?.replaceChildren(recommendation.reason);const guide=card.querySelector('.price-guide');if(guide)guide.className=`price-guide ${recommendation.status}`;card.classList.toggle('loss',c.profit<0);card.querySelector('[data-live-warning]').textContent=row.include&&product&&row.cost?c.errors.filter(error=>!((!Number.isFinite(product.price)||product.price<=0)&&error.includes('SUMdex価格が未入力'))).join(' ／ '):'';}
function renderCatalog(){
 $('productNames').innerHTML=catalog.flatMap(p=>[...productNames(p),p.code].map(name=>`<option value="${esc(name)}${String(p.code??" ").trim()?` [${esc(p.code)}]`:""}"></option>`)).join('');
 const query=nameKey($('catalogSearch').value),visible=catalog.filter(p=>!query||[...productNames(p),p.code].some(n=>nameKey(n).includes(query)));
 $('catalogSummary').textContent=`登録 ${catalog.length}件 ／ 価格確認済 ${catalog.filter(p=>p.checkedAt&&p.price&&p.sourceUrl).length}件 ／ 表示 ${visible.length}件${catalogDirty?' ／ 未保存の変更あり':''}`;
 $('products').innerHTML=visible.map(p=>`<article class="product grid" data-product="${esc(p.id)}"><p class="catalog-title">${esc(p.ja)} ／ ${esc(p.en||'英語名未入力')} <span class="muted">${String(p.code??'').trim()?`[${esc(p.code)}]`:'型番なし'}</span></p>${[['ja','国内買取の表記（日本語など）'],['en','投稿に使う英語名（他サイトの表記でも可）'],['code','型番（任意・ない商品は空欄）'],['domesticNames','国内買取の別表記（複数は | で区切る）'],['price','SUMdex価格（円・後から入力可）'],['sourceUrl','SUMdex価格表URL（後から入力可）']].map(([k,label])=>`<label>${label}<input data-field="${k}" ${k==='price'?'type="number" min="1"':''} value="${esc(p[k])}"></label>`).join('')}<p class="muted">${p.checkedAt&&p.price&&p.sourceUrl?'価格確認済：'+esc(new Date(p.checkedAt).toLocaleString('ja-JP')):'商品名の紐づけを保存できます。販売前にSUMdex価格と価格表URLを確認してください。'}${p.notionRowId?' ／ Notion商品と紐づけ済み':''}${/^https:\/\//.test(p.sourceUrl)?` ／ <a href="${esc(p.sourceUrl)}" target="_blank" rel="noopener noreferrer">この商品の価格表を開く</a>`:''}</p><div class="toolbar"><button data-check="${esc(p.id)}">価格を確認済みにする</button><button data-delete="${esc(p.id)}">この商品を削除</button></div></article>`).join('');
}
async function getLiveLists(sources){const {data,error}=await client.functions.invoke('sumdex-notion-prices',{body:{sources}});if(error||!Array.isArray(data?.lists))throw Error('Notion価格表を取得できません。時間を置いて再試行するか、CSVを取り込んでください。');return data.lists;}
async function refreshSelectedPrice(rowId,productId){
 try{
  if(catalogDirty)throw Error('商品表に未保存の変更があります。商品表を共有保存してから価格を確認してください。');
  const product=catalog.find(p=>p.id===productId);if(!product)throw Error('商品が見つかりません。');
  const sources=sourceKey(product.sourceUrl)?[sourceKey(product.sourceUrl)]:['pokemon','onepiece'];
  const lists=await getLiveLists(sources),hit=matchLiveProduct(product,lists);
  if(!Number.isSafeInteger(hit.row.price)||hit.row.price<=0)throw Error('Notion価格が正しくありません。');
  const checkedAt=new Date().toISOString();
  const needsSave=product.price!==hit.row.price||product.sourceUrl!==hit.list.url||product.notionRowId!==hit.row.id||!product.checkedAt||Date.now()-Date.parse(product.checkedAt)>86400000;
  if(needsSave){
   const next=catalog.map(p=>p.id===productId?{...p,price:hit.row.price,sourceUrl:hit.list.url,notionRowId:hit.row.id,checkedAt}:p);
   validateCatalog(next);await saveDoc('catalog','catalog',{products:next});catalog=next;savedCatalog=JSON.stringify(catalog);catalogDirty=false;renderCatalog();
  }
  const currentRow=rows.find(r=>r.id===rowId),currentProduct=catalog.find(p=>p.id===productId),current=currentRow?calculate(currentRow,currentProduct,settings,domesticForProduct(domestic,currentProduct)):{highest:null};
  rowPriceStatus[rowId]={state:'success',productId,message:`SUMdex ${yen(hit.row.price)} ／ 国内最高 ${current.highest?yen(current.highest):'未確認'}`};
  note(`「${product.ja}」のSUMdex価格と国内表示価格を確認しました。おすすめ設定を確認してください。`);
 }catch(e){rowPriceStatus[rowId]={state:'error',productId,message:`価格を自動確認できません：${e.message||String(e)}`};}
 if(rows.some(r=>r.id===rowId&&r.productId===productId))renderRows();
}
function queuePriceRefresh(row){
 if(!row?.productId)return;
 const rowId=row.id,productId=row.productId;rowPriceStatus[rowId]={state:'loading',productId};renderRows();
 priceRefreshQueue=priceRefreshQueue.then(()=>refreshSelectedPrice(rowId,productId));
}
function renderPriceImport(){
 $('priceImportSummary').textContent=priceImportRows.length?`CSV ${priceImportRows.length}行 ／ 照合 ${priceImportRows.filter(r=>r.productId).length}行 ／ 未照合 ${priceImportRows.filter(r=>!r.productId).length}行。除外した行は価格を更新しません。`:'';
 $('priceImportPreview').innerHTML=priceImportRows.map((row,i)=>`<tr><td>${row.line}</td><td>${esc(row.sourceName||row.sourceCode)}</td><td>${row.price?yen(row.price):'読み取れません'}</td><td><select data-price-row="${i}" aria-label="CSV ${row.line}行目の対応商品"><option value="">除外・未照合</option>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===row.productId?'selected':''}>${esc(p.ja)} / ${esc(p.en)}${String(p.code??" ").trim()?` [${esc(p.code)}]`:""}</option>`).join('')}</select></td><td>${esc(row.reason)}</td></tr>`).join('');
 $('applyPriceList').disabled=!priceImportRows.some(r=>r.productId);
}
function renderSettings(){ $('discounts').innerHTML=Object.entries(CONDITIONS).map(([k,v])=>`<label>${v[0]}の基本割引額（円）<input data-setting="${k}" type="number" min="0" inputmode="numeric" value="${settings[k]}"></label>`).join(''); }
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
 note('準備ができました。商品を検索して選び、仕入れ値と状態を入力してください。');
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==b.dataset.page);document.querySelectorAll('[data-page]').forEach(p=>p.classList.toggle('active',p===b));});
$('addRow').onclick=()=>{rows.push(blank());changed();renderRows();};
$('rows').oninput=e=>{const row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row),t=e.target;if(!row)return;if(t.dataset.search){showSearchResults(t);return;}if(t.type==='checkbox')return;if(t.dataset.field){row[t.dataset.field]=t.value;changed();refreshRowPreview(row);}else if(t.dataset.discount&&t.value!==''&&Number.isFinite(Number(t.value))&&Number(t.value)>=0){row.discounts[t.dataset.discount]=Number(t.value);changed();refreshRowPreview(row);}};
$('rows').onchange=e=>{const row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row)return;const t=e.target;
 if(t.dataset.search)return;
 if(t.dataset.condition)row.conditions=toggleCondition(row.conditions,t.dataset.condition,t.checked);
 else if(t.dataset.discount){const n=Number(t.value);if(!Number.isFinite(n)||n<0){note('割引は0以上の数値にしてください');renderRows();return;}row.discounts[t.dataset.discount]=n;}
 else if(t.dataset.field){row[t.dataset.field]=t.type==='checkbox'?t.checked:t.value;if(t.dataset.field==='productId'){row.basis='auto';delete rowPriceStatus[row.id];changed();rerenderRow(row);queuePriceRefresh(row);return;}}
 changed();rerenderRow(row);};
$('rows').onclick=e=>{const pick=e.target.closest('[data-pick]');if(pick){const row=rows.find(r=>r.id===pick.closest('[data-row]')?.dataset.row);if(row){row.productId=pick.dataset.pick;row.basis='auto';delete rowPriceStatus[row.id];changed();renderRows();$('rows').querySelector(`[data-row="${row.id}"] [data-field="cost"]`)?.focus();queuePriceRefresh(row);}return;}const priceTarget=e.target.closest('[data-price-product]');if(priceTarget){const p=catalog.find(x=>x.id===priceTarget.dataset.priceProduct);if(!p)return;$('catalogSearch').value=p.ja;renderCatalog();document.querySelector('[data-page="catalog"]').click();$('products').firstElementChild?.scrollIntoView({behavior:'smooth',block:'start'});$('products').querySelector('[data-field="price"]')?.focus({preventScroll:true});note(`「${p.ja}」の商品情報を確認してください。価格が未登録でも、Notionで商品を特定できれば本文生成時に自動取得します。`);return;}const action=e.target.dataset.action,row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row||!action)return;
 if(action==='refresh-price'){queuePriceRefresh(row);return;}
 if(action==='duplicate')rows.splice(rows.indexOf(row)+1,0,{...structuredClone(row),id:uid()});if(action==='remove'&&rows.length>1)rows=rows.filter(r=>r!==row);if(action==='reset')delete row.discounts[conditionKey(row)];changed();if(action==='remove')renderRows();else rerenderRow(row);};
$('helpLink').onclick=()=>{$('help').open=true;};
$('saveDraft').onclick=run(async()=>{await saveDoc(draftId,'draft',{title:$('draftTitle').value,rows});dirty=false;updateFlow();await listDrafts();});
$('loadDraft').onclick=run(async()=>{if(!$('draftList').value)return;if(dirty&&!confirm('未保存の変更を破棄して開きますか？'))return;const d=await getDoc($('draftList').value);if(!d)throw Error('下書きが見つかりません');draftId=d.id;versions[d.id]=d.version;rows=d.data.rows.map(row=>normalizeConditionRow({...row,basis:row.basis||'auto'},settings));rowPriceStatus={};$('draftTitle').value=d.data.title;dirty=false;clearOutput();renderRows();});
$('newDraft').onclick=()=>{if(dirty&&!confirm('未保存の変更を破棄しますか？'))return;draftId=uid();rows=[blank()];rowPriceStatus={};$('draftTitle').value='';dirty=false;clearOutput();renderRows();};
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
$('generate').onclick=async()=>{const button=$('generate');button.disabled=true;button.textContent='価格を確認しています…';$('outputErrors').textContent='';clearOutput();$('copyHint').textContent='Notionと国内価格を確認しています。少しお待ちください。';try{const changes=await verifyPrices();await loadDomestic();const out=generate(rows,catalog,settings,domestic);if(out.errors.length){$('outputErrors').textContent=`本文を作れません：${out.errors.join(' ／ ')}`;$('copyHint').textContent='入力や価格を直してから、もう一度生成してください。';$('outputErrors').scrollIntoView({behavior:'smooth',block:'center'});return;}$('output').value=out.text;$('copy').disabled=!out.text;$('charCount').textContent=`${out.text.length.toLocaleString()}文字`;$('copyHint').textContent='本文の金額と状態を確認してからコピーしてください。';
 note(changes.length?`Notionの価格変更を反映しました：${changes.map(x=>`${yen(x.old||0)}→${yen(x.price)}`).join('、')}。本文の価格を確認してください。`:'Notionの最新価格と共有商品表の一致を確認しました。');}catch(e){$('outputErrors').textContent=`本文を作れません：${e.message||String(e)}`;$('copyHint').textContent='入力や商品情報を確認し、もう一度生成してください。';$('outputErrors').scrollIntoView({behavior:'smooth',block:'center'});}finally{button.disabled=false;button.textContent='価格を確認して本文を作る';}};
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
