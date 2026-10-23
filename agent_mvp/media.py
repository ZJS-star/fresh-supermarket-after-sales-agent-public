"""Only registered, currently submitted media enter the model. No inventory/oracle access."""
import base64,hashlib,io,json,subprocess
from pathlib import Path
from PIL import Image,ImageOps
class MediaError(ValueError):pass
MAX_MEDIA_BYTES=25*1024*1024
ALLOWED={'.jpg','.jpeg','.png','.webp','.mp4','.mov'}
def image_part(path):
 with Image.open(path) as source:
  im=ImageOps.exif_transpose(source).convert('RGB');im.thumbnail((1280,1280));out=io.BytesIO();im.save(out,format='JPEG',quality=85)
 return {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode(),'detail':'high'}}
def parts(record,run_dir):
 p=Path(run_dir)/record['local_path']
 if not p.resolve().is_relative_to(Path(run_dir).resolve()) or not p.is_file():raise MediaError('invalid media handle')
 if p.stat().st_size>MAX_MEDIA_BYTES:raise MediaError('media exceeds 25 MiB')
 prefix={'type':'text','text':f"已提交证据 {record['media_id']} (file format {record['kind']}, upload hint is unverified); 自行从画面判断材料类别并记录media_classifications，不按文件名/上传提示认定；observe only visible facts; cite media_id and region/time."}
 if p.suffix.lower() not in ['.mp4','.mov']:return [prefix,image_part(p)],[]
 try:
  probe=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_format','-of','json',str(p)],timeout=15));duration=float(probe['format']['duration']);record['duration_seconds']=duration
  if not 0<duration<=180:raise MediaError('video must be 0..180 seconds')
  frames=Path(run_dir)/'frames';frames.mkdir(exist_ok=True);content=[prefix];refs=[]
  for j,t in enumerate([0,duration/3,2*duration/3,max(0,duration-.2)]):
   dest=frames/(record['media_id']+f'_{j}.jpg');subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(p),'-frames:v','1',str(dest)],check=True,timeout=30);content.append({'type':'text','text':f"video {record['media_id']} time_seconds={t:.3f}"});content.append(image_part(dest));refs.append({'media_id':record['media_id'],'time_seconds':round(t,3)})
  return content,refs
 except (subprocess.SubprocessError,KeyError,ValueError) as e:raise MediaError('video decoding failed: '+type(e).__name__) from None

def register(path,run_dir,media_id,kind=None):
 path=Path(path);run_dir=Path(run_dir)
 if path.suffix.lower() not in ALLOWED:raise MediaError('unsupported media type')
 if path.stat().st_size>MAX_MEDIA_BYTES:raise MediaError('media too large')
 dest=run_dir/'submitted'/f'{media_id}{path.suffix.lower()}';dest.parent.mkdir(parents=True,exist_ok=True)
 if path.resolve()!=dest.resolve():dest.write_bytes(path.read_bytes())
 if path.suffix.lower() not in ['.mp4','.mov']:
  try:
   with Image.open(dest) as im:im.verify()
  except OSError:dest.unlink(missing_ok=True);raise MediaError('image cannot be decoded') from None
 return {'media_id':media_id,'kind':'video' if path.suffix.lower() in ['.mp4','.mov'] else 'receipt' if kind=='receipt' else 'image','local_path':str(dest.relative_to(run_dir)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}

def deduplicate_pixels(messages):
 """Keep all evidence/text handles while sending identical pixels only once per request.
 Journal and checkpoints remain lossless; this is a transport-only projection.
 """
 seen=set();output=[];omitted=0
 for message in messages:
  content=message.get('content')
  if not isinstance(content,list):output.append(message);continue
  projected=[]
  for part in content:
   if part.get('type')=='image_url':
    digest=hashlib.sha256(part['image_url']['url'].encode()).hexdigest()
    if digest in seen:
     projected.append({'type':'text','text':'相同图像内容已在本次上下文的先前证据中提供，请沿用可见画面；本条证据句柄仍有效。'});omitted+=1;continue
    seen.add(digest)
   projected.append(part)
  output.append({**message,'content':projected})
 return output,omitted
