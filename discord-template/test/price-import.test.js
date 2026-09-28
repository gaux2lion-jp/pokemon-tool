import test from 'node:test';
import assert from 'node:assert/strict';
import {parsePriceListCSV,planPriceUpdates} from '../src/price-import.js';

const catalog=[
 {id:'m',ja:'メガドリームex',en:'Mega Dream ex',code:'M4'},
 {id:'a',ja:'デラックスA',en:'Deluxe A',code:'SV11B'},
 {id:'b',ja:'デラックスB',en:'Deluxe B',code:'sv11b'},
 {id:'op',ja:'ワンピース商品',en:"THE WORLD'S STRONGEST WARRIOR",code:'OP-17'}
];

test('English name, case insensitive unique code and inline One Piece code match',()=>{
 const rows=parsePriceListCSV('Name,Price\nMEGA DREAM EX,¥11,800\nOther Title (m4),12000\nTHE WORLD\'S STRONGEST WARRIOR (op-17),12500',catalog);
 // Comma in a currency amount must be quoted as CSV.
 assert.equal(rows[0].price,null);
 assert.deepEqual(rows.map(r=>r.productId),['','m','op']);
 const valid=parsePriceListCSV('Name,Price\nMEGA DREAM EX,"¥11,800"',catalog);
 assert.deepEqual([valid[0].productId,valid[0].price],['m',11800]);
});

test('a repeated set code requires the English name or manual selection',()=>{
 const rows=parsePriceListCSV('Name,Price\nNew listing (sv11B),3000\nDeluxe B (SV11B),3200',catalog);
 assert.deepEqual(rows.map(r=>r.productId),['','b']);
 assert.match(rows[0].reason,/候補が複数/);
});

test('conflicting names and codes are never silently paired',()=>{
 const [row]=parsePriceListCSV('Name,Code,Price\nMega Dream ex,OP-17,11800',catalog);
 assert.equal(row.productId,'');
 assert.match(row.reason,/矛盾/);
});

test('conflicting prices for one matched product block the import',()=>{
 const rows=parsePriceListCSV('Name,Price\nMega Dream ex,11800\nMega Dream ex,11900',catalog);
 assert.throws(()=>planPriceUpdates(rows,catalog),/価格が異なり/);
 rows[1].price=11800;
 assert.equal(planPriceUpdates(rows,catalog).get('m').price,11800);
});
