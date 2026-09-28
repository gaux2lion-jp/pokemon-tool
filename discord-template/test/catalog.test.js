import test from 'node:test';
import assert from 'node:assert/strict';
import {CSV_KEYS,planCatalogImport,validateCatalog} from '../src/catalog.js';

const csv=rows=>[CSV_KEYS,...rows].map(row=>row.map(value=>`"${String(value??'').replaceAll('"','""')}"`).join(',')).join('\r\n');
const notion='https://nifty-lady-7a0.notion.site/SUMdex-Price-List-1fb5128517868045b62ad27795b0f0cd';

test('untouched scraper names are skipped while selected products import',()=>{
 const input=csv([['','商品A'],['','MEGAドリームex','Mega Dream ex','M2a','',11800,notion],['','商品B']]);
 const result=planCatalogImport(input,[],()=>'new-id');
 assert.deepEqual([result.added,result.updated,result.skipped],[1,0,2]);
 assert.deepEqual(result.products.map(p=>[p.id,p.ja,p.en,p.price,p.checkedAt]),[['new-id','MEGAドリームex','Mega Dream ex',11800,'']]);
 assert.throws(()=>validateCatalog(result.products),/確認済みにする/);
});

test('a partially filled selected row shows its CSV line number',()=>{
 const input=csv([['','商品A'],['','商品B','English name']]);
 assert.throws(()=>planCatalogImport(input,[],()=> 'id'),/CSV 3行目/);
});

test('updating a registered price clears confirmation and preserves old aliases in older CSV',()=>{
 const saved={id:'a',ja:'商品A',en:'English A',code:'SET-A',domesticNames:'別表記',price:1000,sourceUrl:notion,checkedAt:'2026-09-28T01:00:00Z'};
 const oldHeader=CSV_KEYS.filter(k=>k!=='domesticNames');
 const input=[oldHeader.join(','),`a,商品A,English A,SET-A,1200,${notion},2026-09-28T01:00:00Z`].join('\n');
 const result=planCatalogImport(input,[saved],()=> 'unused');
 assert.equal(result.updated,1);
 assert.equal(result.products[0].domesticNames,'別表記');
 assert.equal(result.products[0].checkedAt,'');
});
