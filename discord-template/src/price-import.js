import {nameKey,parseCSV} from './pricing.js';

const normalizedHeader=value=>nameKey(value).replace(/[^\p{L}\p{N}]/gu,'');
const NAME_HEADERS=new Set(['商品名','名称','name','productname','title','item']);
const CODE_HEADERS=new Set(['型番','品番','code','setcode','productcode']);
const PRICE_HEADERS=new Set(['price','価格','販売価格','税込価格','saleprice','pricejpy','jpy','priceyen']);
const escapeRegExp=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

export function parsePriceListCSV(source,catalog){
 const [headers,...records]=parseCSV(source.replace(/^\ufeff/,''));
 if(!headers)throw Error('価格表CSVに見出しがありません');
 const index=values=>headers.findIndex(h=>values.has(normalizedHeader(h)));
 const nameColumn=index(NAME_HEADERS),codeColumn=index(CODE_HEADERS),priceColumn=index(PRICE_HEADERS);
 if(priceColumn<0||nameColumn<0&&codeColumn<0)throw Error('価格表CSVに商品名（または型番）と価格の列が必要です。CSVの見出しを確認してください。');
 const rows=[];
 records.forEach((record,n)=>{
  const sourceName=(record[nameColumn]||'').trim(),sourceCode=codeColumn>=0?(record[codeColumn]||'').trim():'';
  const raw=(record[priceColumn]||'').trim();
  if(!sourceName&&!sourceCode&&!raw)return;
  if(record.length!==headers.length){rows.push({line:n+2,sourceName,sourceCode,price:null,productId:'',reason:'CSVの列数が合いません（カンマを含む価格は引用符で囲む）'});return;}
  const priceText=raw.replace(/[¥￥,\s円]/g,'');
  if(!/^\d+$/.test(priceText)||Number(priceText)<=0){rows.push({line:n+2,sourceName,sourceCode,price:null,productId:'',reason:'価格を読み取れません'});return;}
  const price=Number(priceText);
  const inlineCodes=[...new Set(catalog.map(p=>p.code).filter(Boolean))].filter(code=>sourceName&&new RegExp(`(^|[^\\p{L}\\p{N}])${escapeRegExp(code)}($|[^\\p{L}\\p{N}])`,'iu').test(sourceName));
  const withoutCode=inlineCodes.reduce((text,code)=>text.replace(new RegExp(`(?:\\s*[([（]\\s*${escapeRegExp(code)}\\s*[)\\]）]|\\s+${escapeRegExp(code)}\\s*$)`,'iu'),''),sourceName).trim();
  const exactName=catalog.filter(p=>sourceName&&[p.ja,p.en,...String(p.domesticNames||'').split('|')].some(name=>name&&[sourceName,withoutCode].some(source=>nameKey(name)===nameKey(source))));
  const codes=[sourceCode,...inlineCodes];
  const exactCode=catalog.filter(p=>p.code&&codes.some(code=>nameKey(p.code)===nameKey(code)));
  let candidates=exactName;
  if(exactCode.length){const both=exactName.filter(p=>exactCode.some(c=>c.id===p.id));candidates=both.length?both:exactName.length?[]:exactCode;}
  const matched=candidates.length===1?candidates[0]:null;
  rows.push({line:n+2,sourceName,sourceCode,price,productId:matched?.id||'',reason:matched?'自動照合':candidates.length>1?'候補が複数あります':exactName.length&&exactCode.length?'名前と型番が矛盾しています':'未照合'});
 });
 if(!rows.length)throw Error('価格表CSVに商品行がありません');
 return rows;
}

export function planPriceUpdates(rows,catalog){
 const prices=new Map(),conflicts=[];
 for(const row of rows){
  if(!row.productId)continue;
  if(!Number.isFinite(row.price)||row.price<=0)throw Error(`CSV ${row.line}行目：価格を確認してください`);
  if(!catalog.some(p=>p.id===row.productId))throw Error(`CSV ${row.line}行目：商品が見つかりません`);
  const old=prices.get(row.productId);
  if(old&&old.price!==row.price)conflicts.push(`CSV ${old.line}行目と${row.line}行目で同じ商品の価格が異なります`);
  else prices.set(row.productId,{price:row.price,line:row.line});
 }
 if(conflicts.length)throw Error(conflicts.join(' ／ '));
 return prices;
}
