"""Scan tracked files and reachable Git objects; never print matched credentials."""
import json,re,subprocess,sys
from pathlib import Path
PATTERNS={
 'provider_key':rb'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{40,}|AIza[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16})\b',
 'private_key':rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
 'credential_url':rb'https?://[^\s/<>:]{1,80}:[^\s/<>@]{4,100}@',
 'private_export_path':rb'/Users/[A-Za-z0-9._-]{2,}/(?:Documents|Desktop|Downloads)/',
}
def main():
 files=subprocess.check_output(['git','ls-files','-z']).decode().strip('\0').split('\0');findings=[];count=0
 def scan(data,path):
  for kind,pattern in PATTERNS.items():
   # The ignore list may name the excluded private material directory, not its content.
   if kind=='private_export_path' and path=='.gitignore':continue
   if re.search(pattern,data):findings.append({'file':path,'rule':kind})
 for name in files:
  p=Path(name)
  if p.is_symlink() and p.readlink().is_absolute():findings.append({'file':name,'rule':'absolute_symlink'})
  if p.is_file():scan(p.read_bytes(),name)
 try:objects=subprocess.check_output(['git','rev-list','--objects','--all'],stderr=subprocess.DEVNULL).splitlines()
 except subprocess.CalledProcessError:objects=[]
 proc=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
 for line in objects:
  oid,_,path=line.partition(b' ');proc.stdin.write(oid+b'\n');proc.stdin.flush();header=proc.stdout.readline().split()
  if len(header)<3:continue
  data=proc.stdout.read(int(header[2]));proc.stdout.read(1)
  if header[1]==b'blob':count+=1;scan(data,path.decode(errors='replace'))
 proc.stdin.close();proc.wait()
 print(json.dumps({'tracked_files':len(files),'git_blobs_scanned':count,'findings':findings,'scope':'tracked files and reachable Git objects only; ignores local credentials/runtime by design'},ensure_ascii=False))
 return bool(findings)
if __name__=='__main__':sys.exit(main())
