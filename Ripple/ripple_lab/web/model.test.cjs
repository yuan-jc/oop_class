const test = require('node:test');
const assert = require('node:assert/strict');
const m = require('./model.js');
test('实时尾随和历史双向分页使用服务端游标',()=>{
 assert.deepEqual(m.eventQuery('tail',[]),{tail:'1',limit:'100'});
 assert.deepEqual(m.eventQuery('before',[{index:120},{index:150}]),{before:'120',limit:'100'});
 assert.deepEqual(m.eventQuery('after',[{index:120},{index:150}]),{after:'150',limit:'100'});
});
test('删除节点同时清理有向链路并重新选择服务器',()=>{
 const c={nodes:[{id:'s1',role:'server'},{id:'s2',role:'server'},{id:'p1',role:'publisher',server:'s1'}],links:[{source:'s1',target:'p1'}]};
 m.removeNode(c,'s1'); assert.equal(c.nodes[1].server,'s2'); assert.equal(c.links.length,0);
});
test('事件缓冲区有界并按索引去重',()=>{assert.deepEqual(m.mergeEvents([{index:1}],[{index:1},{index:2},{index:3}],2),[{index:2},{index:3}]);});
test('预设有合法角色与独立有向限速',()=>{const c=m.preset('limited');assert.equal(c.links[0].bandwidth_kbit,512);assert.equal(c.nodes.filter(n=>n.role==='server').length,1);});
test('所有预设的引用有效，三服务器与多订阅者数量正确',()=>{
 for(const name of ['single','three','many','limited']){const c=m.preset(name),ids=new Set(c.nodes.map(n=>n.id));assert.equal(ids.size,c.nodes.length);c.nodes.filter(n=>n.server).forEach(n=>assert.ok(ids.has(n.server)));c.links.forEach(l=>{assert.ok(ids.has(l.source));assert.ok(ids.has(l.target));});}
 assert.equal(m.preset('three').nodes.filter(n=>n.role==='server').length,3);
 assert.equal(m.preset('many').nodes.filter(n=>n.role==='subscriber').length,6);
});
test('克隆后修改编辑配置不会污染运行配置',()=>{const c=m.preset('single'),copy=m.clone(c);copy.nodes[0].label='修改';assert.notEqual(c.nodes[0].label,copy.nodes[0].label);});
test('静态资源不存在外部脚本和不安全 HTML 插值',()=>{
 const fs=require('node:fs'),path=require('node:path');
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');assert.doesNotMatch(html,/<script[^>]+src="https?:/);
 for(const name of ['app.js','editor.js','monitor.js']){const source=fs.readFileSync(path.join(__dirname,name),'utf8');assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|document\.write/);}
});
