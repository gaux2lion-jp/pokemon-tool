import {createClient} from '@supabase/supabase-js';
import {SUPABASE_URL,SUPABASE_KEY} from './config.js';
import {CONDITIONS,DEFAULTS,calculate,generate,toggleCondition,yen,parseCSV} from './pricing.js';
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const note=s=>$('notice').textContent=s;
const uid=()=>crypto.randomUUID();
let client,user,members=[],catalog=[],settings={...DEFAULTS},rows=[],domestic={},versions={},draftId=uid(),dirty=false,catalogDirty=false,settingsDirty=false,domesticDate='未取得';
let savedCatalog='';
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
  const p=catalog.find(p=>p.id===row.productId),d=domestic[p?.ja],c=calculate(row,p,settings,d);
  return `<article class="item ${c.profit<0?'loss':''}" data-row="${row.id}"><div class="item-head"><h3>商品 ${i+1}</h3><div class="toolbar"><button data-action="duplicate">複製</button><button data-action="remove">行を削除</button><label class="include"><input data-field="include" type="checkbox" ${row.include?'checked':''}>掲載する</label></div></div>
  <div class="grid"><label>商品<select data-field="productId"><option value="">選択してください</option>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===row.productId?'selected':''}>${esc(p.ja)} / ${esc(p.en)} [${esc(p.code)}]</option>`).join('')}</select></label>
  <label>税込仕入れ値（円 / BOX）<input data-field="cost" type="number" min="1" value="${esc(row.cost)}"></label><label>送料・決済など負担費用（円 / BOX）<input data-field="expenses" type="number" min="0" value="${esc(row.expenses)}"></label>
  <label>優先する価格<select data-field="basis"><option value="sumdex" ${row.basis==='sumdex'?'selected':''}>SUMdexから割引</option><option value="domestic" ${row.basis==='domestic'?'selected':''}>国内表示最高値を下回らない</option></select></label></div>
  <div class="conditions">${Object.entries(CONDITIONS).map(([k,v])=>`<label><input type="checkbox" data-condition="${k}" ${row.conditions.includes(k)?'checked':''}>${v[0]}</label>`).join('')}</div>
  <details><summary>この行の割引を調整</summary><div class="grid">${['clean',...row.conditions.filter(k=>k!=='clean')].map(k=>`<label>${k==='clean'?'基本割引':CONDITIONS[k][0]+' 追加割引'}<input data-discount="${k}" type="number" min="0" value="${row.discounts[k]??settings[k]}"></label>`).join('')}</div><button data-action="reset">行の調整をリセット</button></details>
  <div class="grid"><label>販売価格を手動調整（空欄なら自動）<input data-field="manualPrice" type="number" min="1" value="${esc(row.manualPrice)}" placeholder="${c.sale??''}"></label><label>状態の補足（英語・投稿に表示）<input data-field="notes" value="${esc(row.notes)}" placeholder="例：Dent on the top right corner."></label></div>
  <div class="metrics">${[['SUMdex',p?.price?yen(p.price):'未登録'],['Discord',c.sale!=null?yen(c.sale):'―'],['還付見込',yen(c.refund)],['還付込み利益',c.profit!=null?yen(c.profit):'―'],['国内表示最高',c.highest?yen(c.highest):'―']].map(([a,b])=>`<div><span>${a}</span><strong>${b}</strong></div>`).join('')}</div>
  <p class="muted">還付見込＝税込仕入れ値 ÷ 11。${c.profit===0?'利益なし。':''}国内価格は買取確約ではありません。</p>
  ${c.highest&&c.sale<c.highest?'<p class="warning">国内販売も比較してください。ダメージ減額・保証条件の確認後に判断します。</p>':''}
  ${c.errors.length?`<p class="warning">${c.errors.map(esc).join('<br>')}</p>`:''}
  ${d?`<details><summary>店舗ごとの表示価格・保証表示</summary>${d.shops.map(s=>`<p>${esc(s.site)}：${yen(s.price)} ／ ${esc(s.guarantee)} ／ この状態への適用：要確認</p>`).join('')}</details>`:''}</article>`;
 }).join('');
}
function renderCatalog(){
 $('products').innerHTML=catalog.map(p=>`<article class="product grid" data-product="${esc(p.id)}">${[['ja','日本語の商品名'],['en','英語の商品名'],['code','型番'],['price','SUMdex価格（円）'],['sourceUrl','価格表URL'],['checkedAt','価格表の確認日時（ISO形式）']].map(([k,label])=>`<label>${label}<input data-field="${k}" ${k==='price'?'type="number" min="1"':''} value="${esc(p[k])}"></label>`).join('')}<button data-check="${esc(p.id)}">価格表を確認済みにする</button></article>`).join('');
}
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
 renderCatalog();renderSettings();renderRows();await Promise.all([loadDomestic(),listDrafts()]);
 note('共有ワークスペースに接続しました。変更後は「共有保存」を押してください。');
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==b.dataset.page);document.querySelectorAll('[data-page]').forEach(p=>p.classList.toggle('active',p===b));});
$('addRow').onclick=()=>{rows.push(blank());changed();renderRows();};
$('rows').onchange=e=>{const row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row)return;const t=e.target;
 if(t.dataset.condition)row.conditions=toggleCondition(row.conditions,t.dataset.condition,t.checked);
 else if(t.dataset.discount){const n=Number(t.value);if(!Number.isFinite(n)||n<0){note('割引は0以上の数値にしてください');renderRows();return;}row.discounts[t.dataset.discount]=n;}
 else if(t.dataset.field)row[t.dataset.field]=t.type==='checkbox'?t.checked:t.value;
 changed();renderRows();};
$('rows').onclick=e=>{const action=e.target.dataset.action,row=rows.find(r=>r.id===e.target.closest('[data-row]')?.dataset.row);if(!row||!action)return;
 if(action==='duplicate')rows.splice(rows.indexOf(row)+1,0,{...structuredClone(row),id:uid()});if(action==='remove')rows=rows.filter(r=>r!==row);if(action==='reset')row.discounts={};changed();renderRows();};
$('saveDraft').onclick=run(async()=>{await saveDoc(draftId,'draft',{title:$('draftTitle').value,rows});dirty=false;await listDrafts();});
$('loadDraft').onclick=run(async()=>{if(!$('draftList').value)return;if(dirty&&!confirm('未保存の変更を破棄して開きますか？'))return;const d=await getDoc($('draftList').value);if(!d)throw Error('下書きが見つかりません');draftId=d.id;versions[d.id]=d.version;rows=d.data.rows;$('draftTitle').value=d.data.title;dirty=false;clearOutput();renderRows();});
$('newDraft').onclick=()=>{if(dirty&&!confirm('未保存の変更を破棄しますか？'))return;draftId=uid();rows=[blank()];$('draftTitle').value='';dirty=false;clearOutput();renderRows();};
$('draftTitle').oninput=changed;
$('refreshPrices').onclick=run(loadDomestic);
$('addProduct').onclick=()=>{catalog.push({id:uid(),ja:'',en:'',code:'',price:'',sourceUrl:'',checkedAt:''});catalogDirty=true;clearOutput();renderCatalog();};
$('products').onchange=e=>{const p=catalog.find(p=>p.id===e.target.closest('[data-product]')?.dataset.product);if(!p||!e.target.dataset.field)return;const k=e.target.dataset.field;p[k]=k==='price'?Number(e.target.value):e.target.value.trim();if(k==='price')p.checkedAt='';catalogDirty=true;clearOutput();renderRows();};
$('products').onclick=e=>{const p=catalog.find(p=>p.id===e.target.dataset.check);if(!p)return;if(!p.sourceUrl||!p.price){note('価格と価格表URLを先に入力してください');return;}p.checkedAt=new Date().toISOString();catalogDirty=true;renderCatalog();};
function validateCatalog(){const names=new Set();for(const p of catalog){if(!p.ja||!p.en||!p.code||!Number.isFinite(p.price)||p.price<=0)throw Error('日本語名・英語名・型番・正の価格を入力してください');if(names.has(p.ja))throw Error(`日本語の商品名が重複しています：${p.ja}`);names.add(p.ja);if(!/^https:\/\//.test(p.sourceUrl)||!Number.isFinite(Date.parse(p.checkedAt)))throw Error('価格表URLと確認日時が必要です');}}
$('saveCatalog').onclick=run(async()=>{validateCatalog();await saveDoc('catalog','catalog',{products:catalog});catalogDirty=false;savedCatalog=JSON.stringify(catalog);renderRows();});
$('discounts').onchange=e=>{const n=Number(e.target.value);if(!Number.isFinite(n)||n<0){renderSettings();return;}settings[e.target.dataset.setting]=n;settingsDirty=true;clearOutput();renderRows();};
$('saveSettings').onclick=run(async()=>{await saveDoc('settings','settings',settings);settingsDirty=false;});
async function verifyPrices(){
 if(catalogDirty||settingsDirty)throw Error('商品表・割引設定の変更を共有保存してから生成してください');
 const latestSettings=await getDoc('settings');if((latestSettings?.version||0)!==(versions.settings||0)){settings={...DEFAULTS,...latestSettings?.data};versions.settings=latestSettings?.version||0;renderSettings();renderRows();clearOutput();throw Error('共有の割引設定が更新されました。新しい割引と価格を確認し、もう一度生成してください');}
 const latest=await getDoc('catalog');if(JSON.stringify(latest?.data.products||[])!==savedCatalog){catalog=latest?.data.products||[];versions.catalog=latest?.version||0;savedCatalog=JSON.stringify(catalog);renderCatalog();renderRows();clearOutput();throw Error('共有の商品表が更新されました。新しい価格を確認し、もう一度生成してください');}
 for(const row of rows.filter(r=>r.include)){const p=catalog.find(p=>p.id===row.productId);if(!p?.checkedAt||Date.now()-Date.parse(p.checkedAt)>86400000||Date.parse(p.checkedAt)>Date.now()+60000)throw Error('掲載商品の価格表を24時間以内に確認し、商品表を保存してください。Notion自動連携は未接続です。');}
}
$('generate').onclick=run(async()=>{clearOutput();await verifyPrices();await loadDomestic();const out=generate(rows,catalog,settings,domestic);$('outputErrors').textContent=out.errors.join(' ／ ');if(out.errors.length)return;$('output').value=out.text;$('copy').disabled=!out.text;$('charCount').textContent=`${out.text.length.toLocaleString()}文字`;
 note('共有の商品表との一致を確認しました。Notion原本は自動検査できないため、登録時の目視確認が必要です。');});
$('copy').onclick=run(async()=>{await verifyPrices();if(!$('output').value)return;await navigator.clipboard.writeText($('output').value);note('コピーしました。Discordに貼り付けてください。');});
$('exportCSV').onclick=()=>{const keys=['id','ja','en','code','price','sourceUrl','checkedAt'];const csv=[keys,...catalog.map(p=>keys.map(k=>p[k]))].map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='sumdex-products.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('importCSV').onchange=run(async e=>{const file=e.target.files[0];if(!file)return;const [header,...data]=parseCSV((await file.text()).replace(/^\ufeff/,''));const keys=['id','ja','en','code','price','sourceUrl','checkedAt'];if(keys.some(k=>!header.includes(k)))throw Error('CSVの列が不足しています。書き出したCSVを使ってください');const incoming=data.map(r=>Object.fromEntries(keys.map(k=>[k,r[header.indexOf(k)]||''])));const next=structuredClone(catalog);const seen=new Set();let updates=0;for(const p of incoming){if(seen.has(p.id||p.ja))throw Error('CSV内で商品が重複しています');seen.add(p.id||p.ja);p.id=p.id||uid();p.price=Number(p.price);const i=next.findIndex(x=>x.id===p.id);if(i>=0){next[i]=p;updates++;}else next.push(p);}if(!confirm(`${incoming.length}商品を取り込みます（既存更新 ${updates}件）。共有保存するまで確定されません。続けますか？`))return;catalog=next;catalogDirty=true;clearOutput();renderCatalog();renderRows();note('取り込み内容を商品表で確認し、共有保存してください。');e.target.value='';});
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
