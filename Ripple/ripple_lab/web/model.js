(function(root){
 'use strict';
 const clone=x=>JSON.parse(JSON.stringify(x));
 function preset(kind){
  const nodes=[{id:'s1',role:'server',label:'服务器 1'},{id:'p1',role:'publisher',label:'发布者 1',server:'s1',size:1024,rate:10,duration:10,seed:42},{id:'c1',role:'subscriber',label:'订阅者 1',server:'s1'}];
  if(kind==='three') nodes.push({id:'s2',role:'server',label:'服务器 2'},{id:'s3',role:'server',label:'服务器 3'});
  if(kind==='many') for(let i=2;i<=6;i++)nodes.push({id:'c'+i,role:'subscriber',label:'订阅者 '+i,server:'s1'});
  return {name:({single:'单服务器实验',three:'三服务器实验',many:'多订阅者实验',limited:'受限链路实验'})[kind]||'新实验',protocol:'hashing',nodes,links:kind==='limited'?[{source:'s1',target:'c1',bandwidth_kbit:512,delay_ms:20,loss_percent:0,queue_bytes:1048576,fault_start:null,fault_duration:0}]:[],wait_seconds:10,baseline_seconds:1,warmup_timeout:60,open_node_pages:true};
 }
 function removeNode(c,id){c.nodes=c.nodes.filter(n=>n.id!==id);c.links=c.links.filter(l=>l.source!==id&&l.target!==id);const s=c.nodes.find(n=>n.role==='server');c.nodes.forEach(n=>{if(n.server===id)n.server=s?.id||'';});}
 function mergeEvents(old,items,limit=500){const map=new Map(old.map(e=>[e.index,e]));items.forEach(e=>map.set(e.index,e));return [...map.values()].slice(-limit);}
 function eventQuery(direction,events){if(direction==='before')return {before:String(events[0]?.index??0),limit:'100'};if(direction==='after')return {after:String(events.at(-1)?.index??0),limit:'100'};return {tail:'1',limit:'100'};}
 const api={clone,preset,removeNode,mergeEvents,eventQuery}; if(typeof module!=='undefined')module.exports=api;else root.LabModel=api;
})(typeof window!=='undefined'?window:globalThis);
