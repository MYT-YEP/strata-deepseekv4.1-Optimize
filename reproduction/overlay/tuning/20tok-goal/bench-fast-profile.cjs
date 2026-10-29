const fs = require('node:fs');
const path = require('node:path');
const started = performance.now();
const file = process.env.HARNESS_BENCH_OUTPUT;
if (!file || !path.resolve(file).toLowerCase().startsWith('f:\\strata\\tuning\\')) throw new Error('Benchmark output must be in F:\\STRATA\\tuning');
const record = {startedAt:new Date().toISOString(),requests:[]};
function save() { fs.writeFileSync(file, JSON.stringify({...record,elapsedMs:performance.now()-started},null,2)); }
const nativeFetch = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  const url = String(input instanceof Request ? input.url : input);
  if (!url.startsWith('http://127.0.0.1:8150/v1/messages')) return nativeFetch(input, init);
  const body = JSON.parse(init.body);
  body.temperature = 0;
  const reqStart = performance.now();
  const r = {model:body.model,maxTokens:body.max_tokens,thinking:body.thinking,toolCount:body.tools?.length||0,startMs:reqStart-started,firstTextMs:null,deltaCount:0,textChars:0};
  record.requests.push(r); save();
  const response = await nativeFetch(input,{...init,body:JSON.stringify(body)});
  r.status=response.status;r.headersMs=performance.now()-reqStart;
  const clone=response.clone();
  (async()=>{
    const reader=clone.body.getReader(); const decoder=new TextDecoder(); let pending='';
    while(true){const chunk=await reader.read(); if(chunk.done)break;pending+=decoder.decode(chunk.value,{stream:true});let pos;
      while((pos=pending.indexOf('\n'))>=0){const line=pending.slice(0,pos).trim();pending=pending.slice(pos+1);if(!line.startsWith('data:'))continue;
        let event;try{event=JSON.parse(line.slice(5).trim());}catch{continue;}
        if(event.type==='message_start')r.usage=event.message?.usage;
        if(event.type==='content_block_delta' && event.delta?.type==='text_delta' && event.delta.text){if(r.firstTextMs===null)r.firstTextMs=performance.now()-reqStart;r.deltaCount++;r.textChars+=event.delta.text.length;}
        if(event.type==='message_delta'){r.usage={...r.usage,...event.usage};r.stopReason=event.delta?.stop_reason;if(event.timings)r.timings=event.timings;}
      }
    }
    r.totalMs=performance.now()-reqStart;save();
  })().catch(error=>{r.monitorError=String(error);save();});
  return response;
};
process.on('exit',save);
require('F:/STRATA/harness-fast-launch.cjs');
