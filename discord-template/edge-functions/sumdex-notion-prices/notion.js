export const SOURCES={
 pokemon:{id:'1fb51285-1786-8045-b62a-d27795b0f0cd',url:'https://nifty-lady-7a0.notion.site/SUMdex-Price-List-1fb5128517868045b62ad27795b0f0cd'},
 onepiece:{id:'2ff51285-1786-80e4-a1b3-d0d1f8e308f3',url:'https://nifty-lady-7a0.notion.site/SUMdex-One-Piece-Card-Price-List-2ff51285178680e4a1b3d0d1f8e308f3'}
};

const value=record=>record?.value?.value;
const plain=rich=>Array.isArray(rich)?rich.map(part=>Array.isArray(part)?String(part[0]??''):'').join('').trim():'';

export function locateCollection(page){
 const map=page?.recordMap;
 if(!map?.collection||!map?.collection_view)throw Error('Notionの価格表が読み取れません');
 for(const [id,entry] of Object.entries(map.collection)){
  const collection=value(entry),schema=collection?.schema;
  const priceKey=Object.keys(schema||{}).find(key=>schema[key]?.name==='Price'&&schema[key]?.type==='number');
  if(!priceKey||schema?.title?.type!=='title')continue;
  const views=Object.entries(map.collection_view).filter(([,entry])=>value(entry)?.format?.collection_pointer?.id===id);
  const selected=views.find(([,entry])=>value(entry)?.name==='一覧表示')||views.find(([,entry])=>value(entry)?.type==='table');
  if(!selected)continue;
  return {id,spaceId:collection.space_id,viewId:selected[0],priceKey};
 }
 throw Error('Notionの価格表の列または一覧表示が見つかりません');
}

export function parseCollection(result,priceKey){
 const group=result?.result?.reducerResults?.collection_group_results;
 if(!Array.isArray(group?.blockIds)||group.hasMore!==false)throw Error('Notion価格表を最後まで読み取れませんでした');
 const blocks=result?.recordMap?.block||{};
 const rows=[];
 for(const id of group.blockIds){
  const row=value(blocks[id]);if(!row||row.type!=='page')throw Error('Notion価格表に読み取れない商品行があります');
  const name=plain(row.properties?.title),raw=plain(row.properties?.[priceKey]);
  if(!name&&!raw)continue;
  if(!name)throw Error('Notion価格表に商品名のない価格行があります');
  if(!raw)continue;
  if(!/^\d+$/.test(raw)||!Number.isSafeInteger(Number(raw))||Number(raw)<=0)throw Error(`「${name}」の価格を読み取れません`);
  rows.push({id,name,price:Number(raw)});
 }
 if(!rows.length)throw Error('Notion価格表に有効な商品価格がありません');
 return rows;
}

export async function fetchNotionSource(source,fetcher=fetch){
 const config=SOURCES[source];if(!config)throw Error('対象外の価格表です');
 const url='https://nifty-lady-7a0.notion.site/api/v3/';
 const post=async(endpoint,payload)=>{
  const response=await fetcher(url+endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(22000)});
  if(!response.ok)throw Error(`Notionの取得に失敗しました (${response.status})`);
  return response.json();
 };
 const page=await post('loadPageChunk',{pageId:config.id,limit:100,cursor:{stack:[]},chunkNumber:0,verticalColumns:false});
 const {id,spaceId,viewId,priceKey}=locateCollection(page);
 const query=await post('queryCollection',{collection:{id,spaceId},collectionView:{id:viewId,spaceId},loader:{type:'reducer',reducers:{collection_group_results:{type:'results',limit:1000}},searchQuery:'',userTimeZone:'Asia/Tokyo'}});
 return {source,url:config.url,fetchedAt:new Date().toISOString(),rows:parseCollection(query,priceKey)};
}
