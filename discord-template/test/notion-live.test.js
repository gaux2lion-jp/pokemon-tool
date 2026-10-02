import test from 'node:test';
import assert from 'node:assert/strict';
import {locateCollection,parseCollection} from '../edge-functions/sumdex-notion-prices/notion.js';
import {matchLiveProduct,matchLiveRowsForPreview} from '../src/live-price.js';

const page={recordMap:{collection:{c:{value:{value:{space_id:'s',schema:{title:{type:'title'},price:{type:'number',name:'Price'}}}}}},collection_view:{v:{value:{value:{name:'一覧表示',format:{collection_pointer:{id:'c'}}}}}}}};
const entry=(name,price)=>({value:{value:{type:'page',properties:{title:[[name]],price:[[String(price)]]}}}});
const result={result:{reducerResults:{collection_group_results:{blockIds:['a','b'],hasMore:false}}},recordMap:{block:{a:entry('Mega Dream ex (m4)',11800),b:entry('Other Box (SV11B)',12000)}}};

test('Notion source finds price column by property name and reads complete query',()=>{
 assert.equal(locateCollection(page).priceKey,'price');
 assert.deepEqual(parseCollection(result,'price').map(x=>x.price),[11800,12000]);
 assert.throws(()=>parseCollection({...result,result:{reducerResults:{collection_group_results:{blockIds:['a'],hasMore:true}}}},'price'),/最後まで/);
});

test('a unique product code matches regardless of case and pins the exact row',()=>{
 const list={source:'pokemon',url:'https://nifty-lady-7a0.notion.site/SUMdex-Price-List-1fb5128517868045b62ad27795b0f0cd',rows:[{id:'a',name:'Mega Dream ex (m4)',price:11800},{id:'b',name:'Other Box (SV11B)',price:12000}]};
 const product={id:'p',en:'Mega Dream ex',ja:'メガドリーム',code:'M4'};
 assert.equal(matchLiveProduct(product,[list]).row.id,'a');
 assert.equal(matchLiveRowsForPreview(list,[product])[0].productId,'p');
 assert.equal(matchLiveProduct({...product,notionRowId:'a'},[list]).row.price,11800);
 assert.throws(()=>matchLiveProduct({...product,notionRowId:'missing'},[list]),/見つかりません/);
});

test('duplicate and shipment-specific prices must be reviewed manually',()=>{
 const product={en:'Deluxe Box',ja:'限定商品',code:'M4'};
 const list={source:'pokemon',rows:[{id:'one',name:'Preorder Deluxe Box (M4)',price:1000},{id:'two',name:'Deluxe Box (M4) ※Shipment on 16th Oct.',price:2000}]};
 assert.throws(()=>matchLiveProduct(product,[list]),/照合/);
 list.rows=[{id:'one',name:'Deluxe Box (M4)',price:1000},{id:'two',name:'Deluxe Box (M4)',price:2000}];
 assert.throws(()=>matchLiveProduct(product,[list]),/候補が複数/);
});

test('code-free products match by name while ambiguous names need review',()=>{
 const product={id:'p',ja:'商品',en:'Special Box',code:''};
 const list={source:'pokemon',rows:[{id:'one',name:'Special Box',price:10000}]};
 assert.equal(matchLiveProduct(product,[list]).row.id,'one');
 assert.throws(()=>matchLiveProduct(product,[{...list,rows:[...list.rows,{id:'two',name:'Special Box',price:12000}]}]),/候補が複数/);
});
