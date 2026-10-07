import test from 'node:test';
import assert from 'node:assert/strict';
import {parseOnepieceFeed,opCode,planOnepieceProducts,ONEPIECE_LIST} from '../src/domestic.js';
import {domesticForProduct,generate,DEFAULTS} from '../src/pricing.js';
import {matchLiveProduct} from '../src/live-price.js';
const now=Date.now();
const feed={category:'onepiece',updated_at:new Date(now).toISOString(),results:[{product_display_name:'新たなる皇帝(OP-09)',site:'店舗',price:10000,variant:'状態減額あり'}]};
const domestic=parseOnepieceFeed(feed,now);
const p={id:'op',ja:'別の日本語表記',en:'Emperors in the New World',code:'op09',sourceUrl:ONEPIECE_LIST,price:12000};
test('One Piece joins by code without depending on English/Japanese exact names',()=>{
 assert.equal(opCode('OP-09'),opCode('ｏｐ０９'));
 assert.equal(domesticForProduct(domestic,p).shops[0].price,10000);
 assert.equal(domesticForProduct(domestic,{...p,code:'OP-08'}),null);
 assert.equal(domesticForProduct(domestic,{...p,sourceUrl:'SUMdex-Price-List',ja:'新たなる皇帝(OP-09)'}),null);
});
test('expired feeds and X posts are not used',()=>{
 assert.throws(()=>parseOnepieceFeed({...feed,updated_at:new Date(now-86400001).toISOString()},now));
 assert.deepEqual(parseOnepieceFeed({...feed,results:[{...feed.results[0],published_at:new Date(now-86400001).toISOString()}]},now),{});
});
test('Notion code hyphens and batch import preserve source and avoid duplicate products',()=>{
 const list={source:'onepiece',rows:[{id:'notion',name:'Emperors in the New World [OP-09]',price:12000}]};
 assert.equal(matchLiveProduct(p,[list]).row.id,'notion');
 const plan=planOnepieceProducts(list,domestic,[],()=> 'op');
 assert.equal(plan.products.length,1);assert.equal(plan.products[0].en,'Emperors in the New World');
 assert.equal(planOnepieceProducts(list,domestic,plan.products,()=> 'dup').products.length,0);
 assert.equal(planOnepieceProducts({...list,rows:[...list.rows,...list.rows]},domestic,[],()=> 'bad').products.length,0);
});
test('One Piece data completes the existing template flow in grade order',()=>{
 const rows=['b','sa','am'].map((grade,i)=>({id:String(i),productId:'op',cost:8800,expenses:0,conditions:[grade],discounts:{},basis:'sumdex',manualPrice:'',include:true,notes:''}));
 const out=generate(rows,[p],DEFAULTS,domestic);
 assert.deepEqual(out.errors,[]);assert.ok(out.text.includes(p.en));
 assert.ok(out.text.indexOf('**S/A')<out.text.indexOf('**AM'));assert.ok(out.text.indexOf('**AM')<out.text.indexOf('**B'));
 assert.ok(out.text.includes('¥11,900'));
});
