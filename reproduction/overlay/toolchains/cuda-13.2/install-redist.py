"""Fetch NVIDIA's CUDA redistributables with resume and SHA-256; unpack under this folder."""
import hashlib,json,os,pathlib,shutil,sys,time,urllib.request,zipfile
ROOT=pathlib.Path(r'F:\STRATA\toolchains\cuda-13.2').resolve()
BASE='https://developer.download.nvidia.com/compute/cuda/redist/'
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))
PACKAGES=['cuda_nvcc','cuda_crt','cuda_cudart','cuda_cccl','libcublas','libnvvm']

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(4*1024*1024):h.update(b)
    return h.hexdigest()
def inside(p):
    p=p.resolve()
    if ROOT not in p.parents and p!=ROOT:raise RuntimeError('Path outside isolated toolkit: '+str(p))
    return p

def main():
    ROOT.mkdir(parents=True,exist_ok=True); cache=inside(ROOT/'downloads'); toolkit=inside(ROOT/'toolkit'); cache.mkdir(exist_ok=True);toolkit.mkdir(exist_ok=True)
    with HTTP.open(BASE+'redistrib_13.2.0.json', timeout=30) as r: manifest=json.load(r)
    (ROOT/'nvidia-redistrib-13.2.0.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for name in PACKAGES:
        entry=manifest[name]['windows-x86_64']; expected=int(entry['size']); expected_hash=entry['sha256']; rel=entry['relative_path']; archive=inside(cache/pathlib.PurePosixPath(rel).name)
        have=archive.stat().st_size if archive.exists() else 0
        if have>expected:raise RuntimeError('Existing archive is larger than official package; keeping it: '+str(archive))
        if have<expected:
            print(json.dumps({'event':'download','package':name,'already_bytes':have,'size':expected}),flush=True)
            import subprocess
            cmd=['curl.exe','--noproxy','*','-4','-fsSL','--retry','3','--connect-timeout','20','--max-time','1800','-C','-','-o',str(archive),BASE+rel]
            if subprocess.run(cmd,check=False).returncode:raise RuntimeError('Download interrupted; partial file retained: '+str(archive))
        if archive.stat().st_size!=expected or digest(archive)!=expected_hash:raise RuntimeError('Official size or SHA-256 mismatch; file retained: '+str(archive))
        print(json.dumps({'event':'verified','package':name,'bytes':expected}),flush=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                parts=pathlib.PurePosixPath(info.filename).parts
                if len(parts)<2 or info.is_dir():continue
                relparts=parts[1:]
                if any(p in ('.','..') or ':' in p or '\\' in p for p in relparts):raise RuntimeError('Unexpected zip path')
                if len(relparts)==1 and relparts[0].lower() in ('license','license.txt','version.json','readme.txt'):continue
                dst=inside(toolkit.joinpath(*relparts)); dst.parent.mkdir(parents=True,exist_ok=True)
                if dst.exists():
                    if dst.stat().st_size!=info.file_size:raise RuntimeError('Conflicting existing toolkit file: '+str(dst))
                    continue
                with z.open(info) as source,dst.open('xb') as target:shutil.copyfileobj(source,target,4*1024*1024)
        print(json.dumps({'event':'extracted','package':name}),flush=True)
    (ROOT/'ready.json').write_text(json.dumps({'cuda':'13.2.0','packages':PACKAGES,'toolkit':str(toolkit)},indent=2),encoding='utf-8')
    return 0
if __name__=='__main__':raise SystemExit(main())


