import {nameKey,productNames} from './pricing.js';
import {opCode} from './domestic.js';

const escapeRegExp=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
const hasCode=(title,code)=>Boolean(code)&&(opCode(code)?opCode(title)===opCode(code):new RegExp(`(^|[^\\p{L}\\p{N}])${escapeRegExp(code)}($|[^\\p{L}\\p{N}])`,'iu').test(title));
const withoutCode=(title,code)=>code?title.replace(new RegExp(`(?:\\s*[([（]\\s*${escapeRegExp(code)}\\s*[)\\]）]|\\s+${escapeRegExp(code)}\\s*$)`,'iu'),'').trim():title;
export const sourceKey=url=>url?.includes('One-Piece-Card-Price-List')?'onepiece':url?.includes('SUMdex-Price-List')?'pokemon':null;

export function matchLiveProduct(product,lists){
 const relevant=lists.filter(list=>!sourceKey(product.sourceUrl)||sourceKey(product.sourceUrl)===list.source);
 const all=relevant.flatMap(list=>list.rows.map(row=>({row,list})));
 const label=product.en||product.ja;
 if(product.notionRowId){
  const pinned=all.filter(x=>x.row.id===product.notionRowId);
  if(pinned.length!==1)throw Error(`「${label}」：紐づけたNotion商品が見つかりません。商品表で再照合してください`);
  return pinned[0];
 }
 const names=new Set(productNames(product).map(nameKey));
 const byName=all.filter(({row})=>names.has(nameKey(row.name))||names.has(nameKey(withoutCode(row.name,product.code))));
 const candidates=byName.length?byName:all.filter(({row})=>hasCode(row.name,product.code)&&!/shipment|pre.?order|発送|予約|出荷|※/iu.test(row.name));
 if(candidates.length!==1)throw Error(`「${label}」：Notion価格表との照合${candidates.length?'候補が複数':'ができません'}。商品表の「Notion価格を今確認」で対応商品を選んでください`);
 return candidates[0];
}

export function matchLiveRowsForPreview(list,catalog){
 const assignments=new Map();
 for(const product of catalog){
  try{
   const hit=matchLiveProduct(product,[list]);
   if(!assignments.has(hit.row.id))assignments.set(hit.row.id,product.id);
   else assignments.set(hit.row.id,'');
  }catch{ /* Ambiguous matches remain unassigned in the review screen. */ }
 }
 return list.rows.map((row,index)=>({line:index+1,sourceName:row.name,sourceCode:'',price:row.price,productId:assignments.get(row.id)||'',reason:assignments.get(row.id)?'自動照合':'未照合・確認',notionRowId:row.id}));
}

