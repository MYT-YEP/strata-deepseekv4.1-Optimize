"""Streaming, non-repetitive benchmark for the local Strata service."""
import argparse, ast, datetime, json, os, pathlib, statistics, sys, time, urllib.request

BASE = 'http://127.0.0.1:8080'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CASES = {
  1: [
    ('zh_privacy', '请面向普通电脑用户，用中文说明本地运行大模型的隐私优势、速度限制、内存和硬盘的不同作用，以及两种适合与两种不适合的应用。每个要点举一个具体例子，约400到600字。不要编造硬件测量结果。'),
    ('python_unique', '请写一个完整的 Python 3 函数 stable_unique(items)，对可哈希元素按首次出现顺序去重，不修改原列表。加入类型提示、简短文档字符串和不少于六个覆盖空输入、重复项、字符串及负数的 assert 测试；解释时间和空间复杂度。'),
    ('en_backpressure', 'Explain how to design backpressure in an asynchronous web service that calls a local language model. Discuss bounded queues, cancellation, deadlines, resource limits, and observability, using one concrete example for each. Keep the answer practical and roughly 300 words.')
  ],
  2: [
    ('zh_backup', '用中文给个人开发者设计一个离线大模型项目的备份方案。分别说明模型权重、配置、会话和程序版本如何处理，如何校验文件，以及怎样演练恢复。写五至七个步骤并解释主要取舍，约400到600字。'),
    ('python_intervals', '请写完整的 Python 3 函数 merge_intervals(intervals)，接收半开整数区间 (start,end)，返回按起点排序并合并重叠或相接区间的新列表，不修改输入。加入类型提示、文档字符串和不少于六个覆盖空输入、嵌套、相接、负数的 assert 测试；说明复杂度。'),
    ('en_atomic', 'Explain how to implement crash-safe configuration file updates on a local machine. Cover temporary files, flushing, atomic replacement, concurrent writers, backup recovery, and how to test failure cases. Provide a concise practical checklist of roughly 300 words.')
  ]
}

def get(path):
    with HTTP.open(BASE+path, timeout=8) as r: return json.load(r)

def save(path, result):
    temp = path.with_name(path.name+'.partial')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def run_case(name, prompt, token_limit):
    status=get('/status')
    if status.get('busy') or status.get('queued'):
        raise RuntimeError('Another inference is active or queued; paused before starting '+name)
    payload={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':prompt}],
             'temperature':0,'reasoning_effort':'none','stream':True,'max_tokens':token_limit}
    req=urllib.request.Request(BASE+'/v1/chat/completions', data=json.dumps(payload,ensure_ascii=False).encode(), headers={'Content-Type':'application/json'})
    start=time.perf_counter(); first=None; last_check=start; chunks=[]; finish=None; usage=None; timings=None; done=False
    with HTTP.open(req,timeout=300) as response:
        for raw in response:
            now=time.perf_counter()
            if now-last_check>2:
                last_check=now
                if get('/status').get('queued',0)>0:
                    raise InterruptedError('Another request is queued; stopped benchmark to let it proceed')
            line=raw.decode('utf-8',errors='strict').strip()
            if not line.startswith('data:'): continue
            data=line[5:].strip()
            if data=='[DONE]': done=True; break
            part=json.loads(data); choices=part.get('choices') or []
            if choices:
                delta=choices[0].get('delta') or {}
                text=delta.get('content') or ''
                if text and first is None:first=now-start
                chunks.append(text)
                if choices[0].get('finish_reason') is not None: finish=choices[0]['finish_reason']
            usage=part.get('usage') or usage; timings=part.get('timings') or timings
    elapsed=time.perf_counter()-start
    if not done or not timings or not usage: raise RuntimeError('Missing stream completion or timing information')
    answer=''.join(chunks)
    code_parse=None
    if name.startswith('python_'):
        candidate=answer.split('```python',1)[1].split('```',1)[0] if '```python' in answer else answer.split('```',1)[1].split('```',1)[0] if '```' in answer else answer
        try: ast.parse(candidate); code_parse=True
        except SyntaxError: code_parse=False
    return {'name':name,'prompt':prompt,'answer':answer,'finish_reason':finish,'usage':usage,'timings':timings,
            'first_text_seconds':round(first,3) if first is not None else None,'elapsed_seconds':round(elapsed,3),
            'stream_completed':done,'python_syntax_valid':code_parse}

def main():
    global BASE
    parser=argparse.ArgumentParser();parser.add_argument('--base',default=BASE,choices=['http://127.0.0.1:8080','http://127.0.0.1:8150','http://127.0.0.1:8151']);parser.add_argument('--label',required=True);parser.add_argument('--round',type=int,choices=[1,2],required=True);parser.add_argument('--max-tokens',type=int,default=768);parser.add_argument('--output',required=True,type=pathlib.Path);args=parser.parse_args()
    BASE=args.base
    if args.output.exists(): raise SystemExit('Refusing to overwrite existing results')
    health=get('/health'); status=get('/status')
    if health.get('loaded') is False or health.get('model')!='deepseek-v4.1-flash' or health.get('max_context')!=65536: raise SystemExit('Expected DeepSeek model and 64K context are not active')
    if status.get('busy') or status.get('queued'): raise SystemExit('Model is busy; no benchmark was started')
    out={'label':args.label,'round':args.round,'start_time':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'health':health,'max_tokens':args.max_tokens,'settings':{'temperature':0,'reasoning_effort':'none'},'cases':[]}
    save(args.output,out)
    try:
        for name,prompt in CASES[args.round]:
            print(json.dumps({'event':'starting','case':name},ensure_ascii=False),flush=True)
            row=run_case(name,prompt,args.max_tokens);out['cases'].append(row);save(args.output,out)
            print(json.dumps({'event':'completed','case':name,'output_tokens':row['usage']['completion_tokens'],'decode_tps':row['timings']['predicted_per_second'],'ttft_s':row['first_text_seconds'],'elapsed_s':row['elapsed_seconds'],'finish':row['finish_reason'],'python_syntax_valid':row['python_syntax_valid']},ensure_ascii=False),flush=True)
    except Exception as error:
        out['error']=str(error);save(args.output,out);print(json.dumps({'event':'stopped','error':str(error)},ensure_ascii=False),file=sys.stderr,flush=True);return 2
    tokens=sum(c['timings']['predicted_n'] for c in out['cases']);decode=sum(c['timings']['predicted_ms'] for c in out['cases'])/1000;wall=sum(c['elapsed_seconds'] for c in out['cases'])
    out['summary']={'output_tokens':tokens,'decode_seconds':round(decode,3),'elapsed_seconds':round(wall,3),'weighted_decode_tps':round(tokens/decode,3),'end_to_end_output_tps':round(tokens/wall,3),'minimum_decode_tps':min(c['timings']['predicted_per_second'] for c in out['cases']),'median_decode_tps':statistics.median(c['timings']['predicted_per_second'] for c in out['cases'])}
    save(args.output,out);print(json.dumps({'event':'summary','summary':out['summary']},ensure_ascii=False),flush=True);return 0
if __name__=='__main__':raise SystemExit(main())

