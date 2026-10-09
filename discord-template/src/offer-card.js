// Deterministic artwork: product names and prices come from the reviewed post.
const plain=s=>String(s??'').replace(/\*\*|~~/g,'');
export function cardSlots(messages){
 return messages.flatMap((m,mi)=>m.embeds.flatMap((e,ei)=>mi===messages.length-1&&ei===m.embeds.length-1?[]:[{mi,ei,embed:e}]));
}
export function drawOfferCard(canvas,embed,image){
 const ctx=canvas.getContext('2d'),W=1000,pad=44,textRight=image?718:956;
 const font=(size,weight=400)=>{ctx.font=weight+' '+size+'px Arial, sans-serif';};
 const wrap=(text,width,size,weight=400)=>{font(size,weight);const lines=[];let line='';for(const char of String(text)){if(char==='\n'){lines.push(line);line='';continue;}if(ctx.measureText(line+char).width>width&&line){lines.push(line.trimEnd());line=char===' '?'':char;}else line+=char;}lines.push(line);return lines;};
 const match=embed.title.match(/^(Pokémon Card|ONE PIECE Card) · (.*)$/s);
 const category=match?.[1]||'SUMdex · Trading Cards',name=match?.[2]||embed.title;
 const titleLines=wrap(name,textRight-pad,45,700);
 const lines=embed.description.split('\n').map(v=>plain(v).trim());
 const listPrice=lines.find(v=>/^SUMdex List:\s*¥[\d,]+/.test(v))?.match(/¥[\d,]+/)?.[0]||'';
 const body=[];let y=100+titleLines.length*54+22;
 for(const line of lines){
  if(!line){y+=8;continue;}
  if(/^SUMdex List:/.test(line))continue;
  const price=line.match(/^[🟢🟡🔴]\s*(S\/A|AM|B)\s+(¥[\d,]+)(?:\s*·\s*−(¥[\d,]+))?$/u);
  if(price){body.push({kind:'price',grade:price[1],sale:price[2],discount:price[3],y});y+=124;}
  else{const ls=wrap(line,textRight-pad,26);body.push({kind:'text',lines:ls,y});y+=ls.length*35;}
 }
 canvas.width=W;canvas.height=Math.max(365,y+32,image?370:0);
 ctx.fillStyle='#202329';ctx.fillRect(0,0,W,canvas.height);
 const accent=category==='ONE PIECE Card'?'#f0b653':'#63d6a6';
 ctx.fillStyle=accent;ctx.fillRect(0,0,8,canvas.height);
 ctx.textBaseline='top';font(25,600);ctx.fillStyle=accent;ctx.fillText(category,pad,30);
 font(45,700);ctx.fillStyle='#ffffff';titleLines.forEach((line,i)=>ctx.fillText(line,pad,83+i*54));
 for(const b of body){
  if(b.kind==='text'){font(26);ctx.fillStyle='#b4bcc9';b.lines.forEach((l,i)=>ctx.fillText(l,pad,b.y+i*35));continue;}
  const colors={'S/A':'#65da83',AM:'#ffd35d',B:'#ff6f78'};
  ctx.fillStyle='#2b3038';ctx.fillRect(pad,b.y-4,textRight-pad,110);
  ctx.fillStyle=colors[b.grade];ctx.fillRect(pad,b.y-4,5,110);
  font(27,700);ctx.fillStyle=colors[b.grade];ctx.fillText(b.grade,62,b.y+14);
  const px=168;
  if(listPrice){
   font(23,500);ctx.fillStyle='#bec7d5';ctx.fillText('LIST '+listPrice,px,b.y+1);
   const width=ctx.measureText('LIST '+listPrice).width;
   ctx.strokeStyle='#a4afbd';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(px+49,b.y+15);ctx.lineTo(px+width,b.y+15);ctx.stroke();
  }
  font(19,700);ctx.fillStyle='#91e4bd';ctx.fillText('DISCORD PRICE',px,b.y+35);
  font(41,700);ctx.fillStyle='#ffffff';ctx.fillText(b.sale,px,b.y+58);
  if(b.discount){
   const label='SAVE '+b.discount; font(23,700);
   const badgeW=ctx.measureText(label).width+30,badgeX=textRight-badgeW-12;
   ctx.fillStyle='#154f3a';ctx.beginPath();ctx.roundRect(badgeX,b.y+62,badgeW,38,11);ctx.fill();
   ctx.fillStyle='#85f3b9';ctx.fillText(label,badgeX+15,b.y+68);
  }
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
