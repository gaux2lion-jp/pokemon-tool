export const ONEPIECE_FEED='https://gaux2lion-jp.github.io/kaitori-tool/prices.json';
export const ONEPIECE_LIST='https://nifty-lady-7a0.notion.site/SUMdex-One-Piece-Card-Price-List-2ff51285178680e4a1b3d0d1f8e308f3';
export const opCode=value=>String(value||'').normalize('NFKC').toUpperCase().match(/(?:^|[^A-Z0-9])((?:PRB|OP|EB)[\s‐‑–—−-]*\d{2})(?![\d]|[-]\d)/)?.[1].replace(/[\s‐‑–—−-]/g,'')||'';
export const categoryOf=p=>p?.sourceUrl?.includes('One-Piece-Card-Price-List')?'onepiece':p?.sourceUrl?.includes('SUMdex-Price-List')?'pokemon':opCode(p?.code)?'onepiece':null;

export function parseOnepieceFeed(data,now=Date.now()){
 if(data.category!=='onepiece'||!Array.isArray(data.results))throw Error('ワンピース価格データの形式が不正です');
 const age=now-Date.parse(data.updated_at);
 if(!Number.isFinite(age)||age< -300000||age>86400000)throw Error('ワンピース国内価格が24時間以上更新されていません');
 const result={};
 for(const row of data.results){
  if(row?.stale||!row?.product_display_name||!Number.isFinite(row.price)||row.price<=0)continue;
  if(row.published_at){const age=now-Date.parse(row.published_at);if(!Number.isFinite(age)||age<0||age>86400000)continue;}
  const key='onepiece:'+row.product_display_name;
  const entry=result[key]??={name:row.product_display_name,category:'onepiece',code:opCode(row.product_display_name),shops:[]};
  entry.shops.push({site:row.site,price:row.price,guarantee:row.variant||'状態・適用条件は要確認',url:row.url});
 }
 return result;
}

// Retained reference rows are visible in the report, but are not current quotes.
export function parsePokemonReport(doc){
 const result={};let current;
 for(const tr of doc.querySelectorAll('table tr')){
  if(tr.classList.contains('product-row')){const name=tr.querySelector('strong')?.textContent.trim();current=name?result[name]={name,category:'pokemon',shops:[]}:null;}
  else if(current&&!tr.classList.contains('stale-row')){
   const cells=tr.querySelectorAll('td');if(cells.length<3)continue;
   const amount=(cells[2].querySelector('.price')?.textContent||cells[2].textContent).match(/^\s*(?:[¥￥]\s*)?([\d,]+)\s*円/);
   const price=Number(amount?.[1].replaceAll(',',''));
   if(price>0)current.shops.push({site:(cells[0].childNodes[0]?.textContent||cells[0].textContent).trim(),price,guarantee:cells[0].querySelector('.condition-badge')?.textContent.trim()||'保証表示なし'});
  }
 }
 return Object.fromEntries(Object.entries(result).filter(([,entry])=>entry.shops.length));
}

export function planOnepieceProducts(list,domestic,catalog,idFactory){
 const products=[], skipped=[];
 for(const entry of Object.values(domestic).filter(e=>e.category==='onepiece')){
  if(catalog.some(p=>categoryOf(p)==='onepiece'&&opCode(p.code)===entry.code))continue;
  const matches=list.rows.filter(r=>opCode(r.name)===entry.code&&!/shipment|pre.?order|発送|予約|出荷|カートン|carton|case/iu.test(r.name));
  if(!entry.code||matches.length!==1){skipped.push(entry.name);continue;}
  const row=matches[0];
  const en=row.name.replace(/\s*[\[(（]?(?:PRB|OP|EB)[\s-]*\d{2}[\])）]?\s*/ig,' ').trim();
  if(!/[a-z]/i.test(en)||!Number.isFinite(row.price)||row.price<=0){skipped.push(entry.name);continue;}
  products.push({id:idFactory(),ja:entry.name,en,code:entry.code.replace(/(\D+)(\d+)/,'$1-$2'),domesticNames:'',price:row.price,sourceUrl:ONEPIECE_LIST,checkedAt:new Date().toISOString(),notionRowId:row.id});
 }
 return {products,skipped};
}

