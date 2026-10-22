const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element{
 constructor(){this.children=[];this.value='';this.options=this.children;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 get firstChild(){return this.children[0];}
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('尾随越过大量事件、历史前后翻页和回到最新均请求正确服务端游标',async()=>{
 const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
 const urls=[],state={id:'test',name:'实验',status:'running',stage:'sending',nodes:[],config:{},summary:{}};
 const rows=(first,last)=>Array.from({length:last-first+1},(_,i)=>({index:first+i,node:'s1',event:'send'}));
 const api=async url=>{urls.push(url);if(url.includes('/events?')){const q=new URL(url,'http://localhost').searchParams;if(q.has('before'))return {events:rows(101,200),total:10000,has_more:true};if(q.has('after'))return {events:rows(201,300),total:10000,has_more:true};return {events:rows(9901,10000),total:10000,has_more:true};}if(url.includes('/logs?'))return {text:''};return state;};
 const context={document:{getElementById:get},window:{},LabModel:require('./model.js'),LabEditor:{el:()=>new Element()},Lab:{api,notify(){}},URLSearchParams,location:{search:''},setTimeout,clearTimeout,sessionStorage:{getItem(){return null;},setItem(){}}};
 context.window.Lab=context.Lab;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'monitor.js'),'utf8'),context);const monitor=context.window.LabMonitor;monitor.init();monitor.bind(state);await settle();
 assert.match(urls.find(u=>u.includes('/events?')),/tail=1/);assert.match(get('event-count').textContent,/10000/);assert.equal(get('events').children.length,100);
 get('page-prev').onclick();await settle();assert.match(urls.at(-1),/before=9901/);
 get('page-next').onclick();await settle();assert.match(urls.at(-1),/after=200/);
 const count=urls.filter(u=>u.includes('/events?')).length;await monitor.tick();assert.equal(urls.filter(u=>u.includes('/events?')).length,count);
 get('event-reset').onclick();await settle();assert.match(urls.filter(u=>u.includes('/events?')).at(-1),/tail=1/);assert.match(get('page-label').textContent,/实时尾随/);
});
