import test from 'node:test';
import assert from 'node:assert/strict';
import {parseOnepieceFeed,parsePokemonReport,opCode,planOnepieceProducts,ONEPIECE_LIST} from '../src/domestic.js';
import {domesticForProduct,calculate,generate,DEFAULTS} from '../src/pricing.js';
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


test('retained One Piece rows cannot set the current domestic highest or sale price',()=>{
 const current=feed.results[0],stale={...current,site:'前回店舗',price:20000,stale:true,fetched_at:new Date(now-1000).toISOString()};
 const parsed=parseOnepieceFeed({...feed,results:[stale,{...current,stale:false}]},now);
 const shops=domesticForProduct(parsed,p);
 assert.deepEqual(shops.shops.map(s=>s.price),[10000]);
 const value=calculate({cost:8800,conditions:['sa'],basis:'domestic'},p,DEFAULTS,shops);
 assert.equal(value.highest,10000);assert.equal(value.sale,11900);
 assert.deepEqual(parseOnepieceFeed({...feed,results:[stale]},now),{});
});

// DOM-shaped fixtures exercise the same document parser used by loadDomestic.
const pokemonHeader=name=>({classList:{contains:c=>c==='product-row'},querySelector:selector=>selector==='strong'?{textContent:name}:null});
function pokemonShop(site,price,{stale=false,guarantee='',timestamp=''}={}){
 const cells=[{childNodes:[{textContent:site}],textContent:site,querySelector:selector=>selector==='.condition-badge'&&guarantee?{textContent:guarantee}:null},{textContent:'―'},{textContent:price+timestamp,querySelector:()=>null}];
 return {classList:{contains:c=>stale&&c==='stale-row'},querySelectorAll:selector=>selector==='td'?cells:[]};
}
const pokemonDocument=rows=>({querySelectorAll:selector=>selector==='table tr'?rows:[]});
test('Pokemon report excludes stale rows and stale-only products while preserving live quotes',()=>{
 const parsed=parsePokemonReport(pokemonDocument([
  pokemonHeader('商品A'),pokemonShop('前回店舗','20,000円',{stale:true,guarantee:'前回掲載: 満額保証'}),
  pokemonShop('現在店舗','8,000円',{guarantee:'満額保証',timestamp:'取得日時: 2026-10-14 23:00 日本時間'}),
  pokemonHeader('前回だけの商品'),pokemonShop('前回店舗','30,000円',{stale:true}),
 ]));
 assert.deepEqual(Object.keys(parsed),['商品A']);
 assert.deepEqual(parsed['商品A'].shops,[{site:'現在店舗',price:8000,guarantee:'満額保証'}]);
 const product={...p,ja:'商品A',code:'',sourceUrl:'SUMdex-Price-List'};
 assert.equal(calculate({cost:8800,conditions:['sa'],basis:'domestic'},product,DEFAULTS,domesticForProduct(parsed,product)).highest,8000);
});
test('Pokemon all-stale report produces no current quotes; unflagged legacy rows still import',()=>{
 assert.deepEqual(parsePokemonReport(pokemonDocument([pokemonHeader('商品'),pokemonShop('前回','10,000円',{stale:true})])),{});
 const parsed=parsePokemonReport(pokemonDocument([pokemonHeader('商品'),pokemonShop('店舗','10,000円')]));
 assert.equal(parsed['商品'].shops[0].price,10000);
});

test('Pokemon observation timestamps cannot substitute for a missing currency amount',()=>{
 const parsed=parsePokemonReport(pokemonDocument([pokemonHeader('商品'),pokemonShop('店舗','',{timestamp:'取得日時: 2026-10-14 23:00 日本時間'})]));
 assert.deepEqual(parsed,{});
});
