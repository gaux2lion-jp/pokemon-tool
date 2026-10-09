const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function normalizeImage(file){
 if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024)throw Error('JPEG・PNG・WebPの10MB以下の画像を選んでください');
 const image=await createImageBitmap(file);try{if(image.width*image.height>50000000)throw Error('画像が大きすぎます。縮小して選び直してください');const scale=Math.min(1,1000/Math.max(image.width,image.height));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',0.86));if(!blob||blob.type!=='image/webp'||blob.size>2*1024*1024)throw Error('画像変換に失敗しました。別の画像でお試しください');return blob;}finally{image.close();}
}
export function imageEditor(p,base){return `<section class="product-image"><strong>投稿用の商品画像</strong>${p.imagePath?`<img src="${esc(base+'/storage/v1/object/public/sumdex-products/'+p.imagePath)}" alt="登録した商品画像" loading="lazy"><button type="button" data-image-remove>画像の紐づけを外す</button>`:'<p>未登録：投稿は文章のみになります</p>'}<label class="file">画像ファイルを選ぶ<input data-image-file type="file" accept="image/jpeg,image/png,image/webp"></label><label>または画像URL<input data-image-source type="url" placeholder="https://cdn.snkrdunk.com/…"></label><button type="button" data-image-url>URLから画像を取り込む</button><small>参考画像です。使用可能な画像を登録してください。保存後「商品表を共有保存」を押してください。</small></section>`;}
function markdown(text){return esc(text).replace(/\[([^\]]+)\]\((https:\/\/discord\.com\/channels\/[\d/]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/~~([^~]+)~~/g,'<s>$1</s>').replace(/\n/g,'<br>');}
export function renderPostPreview(element,data){
 const d=data.destination;const destination=document.createElement('p');destination.textContent=`投稿先：${d.name} ／ チャンネルID ${d.channelId}`;element.replaceChildren(destination);
 const link=document.createElement('a');link.href=`https://discord.com/channels/${d.guildId}/${d.channelId}`;link.textContent='投稿先チャンネルを開く';link.target='_blank';link.rel='noopener noreferrer';element.append(link);
 for(const [i,message] of (data.cardMessages||data.messages).entries()){const block=document.createElement('section');block.className='discord-preview';block.innerHTML=`<small>メッセージ ${i+1} / ${data.messages.length}</small><p>${markdown(message.content)}</p>${message.embeds.map(e=>`<article class="discord-embed">${e.thumbnail?`<img class="discord-thumbnail" src="${esc(e.thumbnail.url)}" alt="${esc(e.title)}">`:""}${e.title?`<h3>${esc(e.title)}</h3>`:""}${e.description?`<p>${markdown(e.description)}</p>`:""}${e.image?`<img src="${esc(e.image.url)}" alt="${esc(e.title)}">`:''}</article>`).join('')}`;for(const img of block.querySelectorAll('img'))img.onerror=()=>{img.replaceWith(document.createTextNode('⚠ 画像を表示できません。商品画像を確認してください。'));};element.append(block);}
}

export function renderPostEditor(element,data,onDirty,onApply){
 const panel=document.createElement('details');panel.className='post-editor';
 const summary=document.createElement('summary');summary.textContent='✏️ 投稿文を自由に編集する';panel.append(summary);
 const hint=document.createElement('p');hint.textContent='今回の投稿だけを編集します。「編集を反映して最終確認」を押すとカード画像も作り直します。編集中は文章で表示します。商品表は変わりません。金額を変える場合は上の商品入力で変更し、再生成してください。再生成すると文章の編集はリセットされます。';panel.append(hint);
 const draft=structuredClone(data.messages),inputs=[];
 const toolbar=document.createElement('div');toolbar.className='toolbar';let active;
 for(const [label,before,after] of [['太字','**','**'],['取り消し線','~~','~~'],['🔥','🔥 ',''],['💰','💰 ',''],['📦','📦 ',''],['✨','✨ ','']]){
  const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>{if(!active)return;const start=active.selectionStart,end=active.selectionEnd;active.setRangeText(before+active.value.slice(start,end)+after,start,end,'select');active.dispatchEvent(new Event('input',{bubbles:true}));active.focus();};toolbar.append(b);
 }panel.append(toolbar);
 const preview=document.createElement('div');preview.className='edited-preview';
 const add=(label,value,set)=>{const l=document.createElement('label');l.textContent=label;const t=document.createElement('textarea');t.value=value;t.rows=label.includes('見出し')?2:5;t.onfocus=()=>active=t;t.oninput=()=>{set(t.value);onDirty();renderPostPreview(preview,{...data,cardMessages:null,messages:draft});};l.append(t);panel.append(l);inputs.push(t);};
 data.messages.forEach((m,i)=>{add(`メッセージ${i+1}：冒頭の文章`,m.content,v=>draft[i].content=v);m.embeds.forEach((e,j)=>{add(`メッセージ${i+1}・${j+1}：見出し`,e.title,v=>draft[i].embeds[j].title=v);add(`メッセージ${i+1}・${j+1}：本文`,e.description,v=>draft[i].embeds[j].description=v);});});
 const apply=document.createElement('button');apply.type='button';apply.className='primary';apply.textContent='編集を反映して最終確認';apply.onclick=async()=>{apply.disabled=true;inputs.forEach(t=>t.disabled=true);toolbar.querySelectorAll('button').forEach(b=>b.disabled=true);try{await onApply(draft);}finally{apply.disabled=false;inputs.forEach(t=>t.disabled=false);toolbar.querySelectorAll('button').forEach(b=>b.disabled=false);}};
 panel.append(apply);element.prepend(panel);element.append(preview);
}
