// Deterministic artwork: product names and prices come from the reviewed post.
const plain=s=>String(s??'').replace(/\*\*|~~/g,'');
export function cardSlots(messages){
 return messages.flatMap((m,mi)=>m.embeds.flatMap((e,ei)=>mi===messages.length-1&&ei===m.embeds.length-1?[]:[{mi,ei,embed:e}]));
}
export function drawOfferCard(canvas,embed,image){
 const ctx=canvas.getContext('2d'),W=1000,pad=44,textRight=image?718:950;
 const font=(size,weight=400)=>{ctx.font=`${weight} ${size}px Arial, sans-serif`;};
 const wrap=(text,width,size,weight=400)=>{font(size,weight);const lines=[];let line='';for(const char of String(text)){if(char==='\n'){lines.push(line);line='';continue;}if(ctx.measureText(line+char).width>width&&line){lines.push(line.trimEnd());line=char===' '?'':char;}else line+=char;}lines.push(line);return lines;};
 const match=embed.title.match(/^(Pokémon Card|ONE PIECE Card) · (.*)$/s);
 const category=match?.[1]||'SUMdex · Trading Cards',name=match?.[2]||embed.title;
 const titleLines=wrap(name,textRight-pad,46,700);
 const body=[];let y=98+titleLines.length*54+28;
 for(const raw of embed.description.split('\n')){
  const line=plain(raw).trim();if(!line){y+=12;continue;}
  const price=line.match(/^[🟢🟡🔴]\s*(S\/A|AM|B)\s+(¥[\d,]+)(?:\s*·\s*−(¥[\d,]+))?$/u);
  if(price){body.push({kind:'price',grade:price[1],sale:price[2],discount:price[3],y});y+=76;}
  else{const lines=wrap(line,textRight-pad,27);body.push({kind:'text',lines,y});y+=lines.length*37;}
 }
 canvas.width=W;canvas.height=Math.max(350,y+36,image?380:0);
 ctx.fillStyle='#202329';ctx.fillRect(0,0,W,canvas.height);
 const accent=category==='ONE PIECE Card'?'#f0b653':'#63d6a6';
 ctx.fillStyle=accent;ctx.fillRect(0,0,8,canvas.height);
 ctx.textBaseline='top';font(25,500);ctx.fillStyle=accent;ctx.fillText(category,pad,34);
 font(46,700);ctx.fillStyle='#ffffff';titleLines.forEach((line,i)=>ctx.fillText(line,pad,88+i*54));
 for(const b of body){
  if(b.kind==='text'){font(27);ctx.fillStyle='#b4bcc9';b.lines.forEach((l,i)=>ctx.fillText(l,pad,b.y+i*37));continue;}
  const colors={'S/A':'#65da83',AM:'#ffd35d',B:'#ff6f78'};
  ctx.fillStyle=colors[b.grade];ctx.beginPath();ctx.arc(58,b.y+23,10,0,Math.PI*2);ctx.fill();
  font(31,500);ctx.fillStyle='#e4e8ef';ctx.fillText(b.grade,82,b.y+7);
  font(46,700);ctx.fillStyle='#ffffff';ctx.fillText(b.sale,212,b.y);
  if(b.discount){font(25);ctx.fillStyle='#aab4c4';ctx.textAlign='right';ctx.fillText('−'+b.discount,textRight,b.y+12);ctx.textAlign='left';}
  ctx.fillStyle='#353a43';ctx.fillRect(pad,b.y+62,textRight-pad,1);
 }
 if(image){const box={x:758,y:105,w:198,h:222},scale=Math.min(box.w/image.width,box.h/image.height);ctx.drawImage(image,box.x+(box.w-image.width*scale)/2,box.y+(box.h-image.height*scale)/2,image.width*scale,image.height*scale);}
 return canvas;
}
export async function createOfferCard(embed){
 let bitmap;
 try{
  if(embed.thumbnail?.url){const r=await fetch(embed.thumbnail.url,{signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('商品画像を取得できません');bitmap=await createImageBitmap(await r.blob());}
  const canvas=drawOfferCard(document.createElement('canvas'),embed,bitmap);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',0.94));
  if(!blob||blob.type!=='image/webp'||blob.size>2*1024*1024)throw Error('カード画像が大きすぎます。商品の説明を短くしてください');
  return blob;
 }finally{bitmap?.close();}
}
