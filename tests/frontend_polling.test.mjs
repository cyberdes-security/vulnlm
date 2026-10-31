// Real frontend modules with a fake clock/network; no Docker or model server needed.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {webcrypto} from 'node:crypto';
import vm from 'node:vm';
import test from 'node:test';

const root=new URL('../frontend/',import.meta.url);

class Element {
    constructor() {this.dataset={};this.children=[];this.hidden=false;this.classList={toggle(){}};}
    append(...items) {this.children.push(...items);}
    prepend(...items) {this.children.unshift(...items);}
    replaceChildren(...items) {this.children=items;}
    addEventListener() {}
    setAttribute() {}
    focus() {}
}

async function lab({main=false}={}) {
    const elements=new Map(),timers=new Map(),logs=[];
    let timerId=0,fetches=0,session={id:1},unauthorized=0;
    let network=async path=>response(200,path==='/me'
        ? {id:1,name:'Alice',role:'user',balance:'1000.00'}
        : path==='/lab/scenarios' ? [] : state());
    const element=id=>{
        if(!elements.has(id)) elements.set(id,new Element());
        return elements.get(id);
    };
    const context=vm.createContext({
        document:{getElementById:element,createElement:()=>new Element(),documentElement:{},querySelectorAll:()=>[]},
        localStorage:{getItem:()=>null,setItem(){}},crypto:webcrypto,
        fetch:(...args)=>{fetches++;return network(...args);},
        setTimeout:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},
        clearTimeout:id=>timers.delete(id),
    });
    // One promise per URL: concurrent imports of a shared dependency get the same module instance.
    const modules=new Map();
    function module(url) {
        if(!modules.has(url.href)) modules.set(url.href,create(url));
        return modules.get(url.href);
    }
    async function create(url) {
        const name=url.href;
        let result;
        if(url.pathname.endsWith('/scenarios.js')) {
            result=new vm.SyntheticModule(['localised','renderScenarios','setScenarios','onConfigureScenario'],function(){
                this.setExport('localised',(item,key)=>item[key+'_en']||item[key]);
                for(const name of ['renderScenarios','setScenarios','onConfigureScenario']) this.setExport(name,()=>{});
            },{context,identifier:name});
        } else if(url.pathname.endsWith('/settings.js')) {
            result=new vm.SyntheticModule(['labPolicy','loadSettings','renderSettings','resetSettings','configureSettings','openSettings'],function(){
                this.setExport('labPolicy',null);
                for(const name of ['loadSettings','renderSettings','resetSettings','configureSettings','openSettings']) this.setExport(name,()=>{});
            },{context,identifier:name});
        } else if(url.pathname.endsWith('/documents.js')) {
            result=new vm.SyntheticModule(['renderDocuments'],function(){
                this.setExport('renderDocuments',()=>{});
            },{context,identifier:name});
        } else {
            result=new vm.SourceTextModule(await readFile(fileURLToPath(url),'utf8'),{context,identifier:name});
        }
        return result;
    }
    const entry=await module(new URL(main?'app.js':'js/models.js',root));
    // Link once from the entry; linking each module separately instantiates a parent
    // before a shared dependency (i18n.js) has resolved its own imports.
    await entry.link((specifier,parent)=>module(new URL(specifier,parent.identifier)));
    await entry.evaluate();
    const models=(await modules.get(new URL('js/models.js',root).href)).namespace;
    const api=(await modules.get(new URL('js/api.js',root).href)).namespace;
    if(!main) api.configureApi({getCurrentUser:()=>session,onUnauthorized:()=>{
        unauthorized++;session=null;models.resetModels();
    }});
    if(!main) models.configureModels({getCurrentUser:()=>session,log:message=>logs.push(message),addMessage(){}});
    // Let the real entry point finish its async session/settings/model bootstrap.
    for(let i=0;i<30;i++) await Promise.resolve();
    return {models,api,elements,timers,logs,
        get fetches(){return fetches;},get session(){return main?entry.namespace.currentUser:session;},get unauthorized(){return unauthorized;},
        setNetwork(fn){network=fn;},
        changeSession(value){session=value;models.resetModels();},
        async poll(){
            assert.equal(timers.size,1);
            const [id,{callback,delay}]=timers.entries().next().value;
            timers.delete(id);await callback();return delay;
        },
        nextDelay(){assert.equal(timers.size,1);return timers.values().next().value.delay;},
    };
}

function state() {
    return {active:'qwen2.5:3b',pending:null,models:[],can_manage:false,
            source:{kind:'lab',reachable:true},gateway:true,vision:''};
}
function response(status,data) {
    return {status,ok:status>=200&&status<300,text:async()=>JSON.stringify(data)};
}
function deferred() {
    let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};
}

test('repeated network failures log once, preserve the user and back off',async()=>{
    const app=await lab();
    app.setNetwork(async()=>{throw new TypeError('Load failed');});
    await assert.rejects(app.models.loadModels(),/Load failed/);
    assert.equal(app.logs.length,1);
    assert.equal(app.nextDelay(),15000);
    assert.equal(app.elements.get('model-download').hidden,false);
    await app.poll();assert.equal(app.nextDelay(),30000);
    await app.poll();assert.equal(app.nextDelay(),60000);
    await app.poll();assert.equal(app.nextDelay(),60000);
    assert.equal(app.logs.length,1);
    assert.equal(app.session.id,1);
    assert.equal(app.unauthorized,0);
});

test('recovery logs one transition and returns to the normal interval',async()=>{
    const app=await lab();
    app.setNetwork(async()=>{throw new TypeError('Load failed');});
    await assert.rejects(app.models.loadModels());
    app.setNetwork(async()=>response(200,state()));
    await app.poll();
    assert.equal(app.logs.length,2);
    assert.equal(app.logs[1],'Model status connection restored.');
    assert.equal(app.nextDelay(),15000);
    assert.equal(app.elements.get('model-download').hidden,true);
    await app.poll();assert.equal(app.logs.length,2);
});

test('401 invalidates the session once and stops polling',async()=>{
    const app=await lab();
    await app.models.loadModels();
    app.setNetwork(async()=>response(401,{detail:'Log in with a synthetic lab account'}));
    await app.poll();
    assert.equal(app.unauthorized,1);
    assert.equal(app.session,null);
    assert.equal(app.models.modelState,null);
    assert.equal(app.timers.size,0);
    assert.equal(app.logs.length,0);
});

test('invalid login credentials do not trigger session expiry handling',async()=>{
    const app=await lab();
    app.setNetwork(async()=>response(401,{detail:'Invalid lab credentials'}));
    await assert.rejects(app.api.api('/auth/login',{email:'alice@lab.local',password:'wrong'}),
        error=>error.status===401);
    assert.equal(app.unauthorized,0);
    assert.equal(app.session.id,1);
});

test('an old request cannot sign out a later login',async()=>{
    const app=await lab(),pending=deferred();
    app.setNetwork(()=>pending.promise);
    const request=app.models.loadModels();
    app.changeSession({id:2});
    pending.resolve(response(401,{detail:'Log in with a synthetic lab account'}));
    await request;
    assert.equal(app.session.id,2);
    assert.equal(app.unauthorized,0);
    assert.equal(app.timers.size,0);
});

test('an in-flight success cannot restore model state after logout',async()=>{
    const app=await lab(),pending=deferred();
    app.setNetwork(()=>pending.promise);
    const request=app.models.loadModels();
    app.changeSession(null);
    pending.resolve(response(200,state()));
    await request;
    assert.equal(app.models.modelState,null);
    assert.equal(app.timers.size,0);
});

test('overlapping refresh requests share one fetch and one timer',async()=>{
    const app=await lab(),pending=deferred();
    app.setNetwork(()=>pending.promise);
    const first=app.models.loadModels(),second=app.models.loadModels();
    assert.equal(first,second);
    assert.equal(app.fetches,1);
    pending.resolve(response(200,state()));
    await Promise.all([first,second]);
    assert.equal(app.timers.size,1);
});

test('a repeated HTTP failure is logged once and retains its status',async()=>{
    const app=await lab();
    app.setNetwork(async()=>response(503,{detail:'Temporarily unavailable'}));
    await assert.rejects(app.models.loadModels(),error=>error.status===503);
    await app.poll();
    assert.equal(app.logs.length,1);
    assert.match(app.logs[0],/HTTP 503/);
    assert.equal(app.session.id,1);
});

test('the real app returns to login once after an invalid session',async()=>{
    const app=await lab({main:true});
    assert.equal(app.session.name,'Alice');
    assert.equal(app.elements.get('app-view').hidden,false);
    app.setNetwork(async()=>response(401,{detail:'Log in with a synthetic lab account'}));
    await app.poll();
    assert.equal(app.session,null);
    assert.equal(app.elements.get('login-view').hidden,false);
    assert.equal(app.elements.get('app-view').hidden,true);
    assert.equal(app.elements.get('login-notice').textContent,'Your session is no longer valid. Sign in again.');
    assert.equal(app.elements.get('log-container').children.length,1);
    assert.equal(app.timers.size,0);
});

test('the real app keeps its session and writes one warning during an outage',async()=>{
    const app=await lab({main:true});
    app.setNetwork(async()=>{throw new TypeError('Load failed');});
    await app.poll();await app.poll();await app.poll();
    assert.equal(app.session.name,'Alice');
    assert.equal(app.elements.get('app-view').hidden,false);
    assert.equal(app.elements.get('log-container').children.length,1);
    assert.equal(app.nextDelay(),60000);
});
