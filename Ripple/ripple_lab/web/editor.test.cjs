const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element{
 constructor(){this.children=[];this.listeners={};this.value='';this.checked=false;this.textContent='';this.dataset={};}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(){}
 addEventListener(type,fn){this.listeners[type]=fn;}
}
test('修改设置后增删拓扑仍保留未保存的实验字段',()=>{
 const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
 const add=new Element();add.dataset={add:'server'};
 const document={getElementById:get,createElement:()=>new Element(),createElementNS:()=>new Element(),querySelectorAll:q=>q==='[data-add]'?[add]:[]};
 const context={document,window:{LabModel:require('./model.js'),Lab:{notify(){}}}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'editor.js'),'utf8'),context);
 const editor=context.window.LabEditor;editor.init();
 get('config-name').value='还未保存的新名称';get('wait').value='42';get('baseline').value='3';get('warmup').value='90';get('auto-open').checked=false;
 get('config-name').listeners.input();add.onclick();
 assert.equal(get('config-name').value,'还未保存的新名称');assert.equal(get('wait').value,42);assert.equal(get('baseline').value,3);assert.equal(get('warmup').value,90);assert.equal(get('auto-open').checked,false);
 const row=get('node-editor').children.at(-1);row.children.at(-1).onclick();
 assert.equal(get('config-name').value,'还未保存的新名称');assert.equal(editor.get().wait_seconds,42);
});
test('可视化调节全部参数后能原样读取并回填',()=>{
 const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
 const presets=['single','three','many','limited'].map(name=>{const b=new Element();b.dataset={preset:name};return b;});
 const adds=['server','publisher','subscriber'].map(role=>{const b=new Element();b.dataset={add:role};return b;});
 const document={getElementById:get,createElement:()=>new Element(),createElementNS:()=>new Element(),
  querySelectorAll:q=>q==='[data-preset]'?presets:q==='[data-add]'?adds:[]};
 const context={document,window:{LabModel:require('./model.js'),Lab:{notify(){}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'editor.js'),'utf8'),context);
 const editor=context.window.LabEditor;editor.init();
 const rows=()=>get('node-editor').children;
 const control=(row,label)=>{const field=row.children.find(x=>x.textContent===label);assert.ok(field,'缺少字段 '+label);return field.children[0];};
 const change=(row,label,value)=>{const c=control(row,label);c.value=String(value);c.onchange();};
 get('config-name').value='可视化参数测试';get('wait').value='12';get('baseline').value='2';get('warmup').value='45';get('auto-open').checked=true;
 editor.get(); // 先同步全局字段，后续新增链路会重建界面并从 config 回填
 const publisher=rows()[1];
 control(publisher,'发布者').value='发布者 A';control(publisher,'发布者').onchange();
 change(publisher,'连接服务器','s1');change(publisher,'消息字节',2048);change(publisher,'每秒条数',50);change(publisher,'发送秒数',6);change(publisher,'随机种子',99);
 const subscriber=rows()[2];
 control(subscriber,'订阅者').value='订阅者 A';control(subscriber,'订阅者').onchange();
 change(subscriber,'连接服务器','s1');
 get('add-link').onclick();
 const link=get('link-editor').children[0];
 const edge=link.children[0].children;
 edge[0].value='p1';edge[0].onchange();edge[2].value='c1';edge[2].onchange();
 const linkField=(index,value)=>{const c=link.children[index].children[0];c.value=String(value);c.onchange();};
 linkField(1,512);linkField(2,20);linkField(3,5);linkField(4,65536);linkField(5,1);linkField(6,2);
 const value=editor.get();
 assert.equal(value.name,'可视化参数测试');assert.equal(value.wait_seconds,12);assert.equal(value.baseline_seconds,2);assert.equal(value.warmup_timeout,45);assert.equal(value.open_node_pages,true);
 const p=value.nodes.find(n=>n.id==='p1');
 assert.equal(p.label,'发布者 A');assert.equal(p.server,'s1');assert.equal(p.size,2048);assert.equal(p.rate,50);assert.equal(p.duration,6);assert.equal(p.seed,99);
 assert.equal(value.nodes.find(n=>n.id==='c1').label,'订阅者 A');
 assert.deepEqual(value.links[0],{source:'p1',target:'c1',bandwidth_kbit:512,delay_ms:20,loss_percent:5,queue_bytes:65536,fault_start:1,fault_duration:2});
 editor.set(value);assert.deepEqual(editor.get(),value);
 presets.find(b=>b.dataset.preset==='three').onclick();
 assert.equal(editor.get().nodes.filter(n=>n.role==='server').length,3);
 presets.find(b=>b.dataset.preset==='many').onclick();
 assert.equal(editor.get().nodes.filter(n=>n.role==='subscriber').length,6);
 presets.find(b=>b.dataset.preset==='limited').onclick();
 assert.equal(editor.get().links[0].bandwidth_kbit,512);
});
