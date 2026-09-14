import os, json, random, sqlite3, subprocess, textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template_string
import requests
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.background import BackgroundScheduler

APP_DIR = Path(__file__).parent
MEDIA_DIR = APP_DIR / 'media'
MEDIA_DIR.mkdir(exist_ok=True)
DB = APP_DIR / 'invome.db'

app = Flask(__name__)

DEFAULTS = {
    'brand_name': 'Invome',
    'site_url': 'https://invome-560ba.web.app/start.html',
    'offer': '7-day free trial • $9.99/month or $99.99/year',
    'audience': 'small business owners who need a simpler way to track inventory',
    'platforms': 'facebook,instagram,tiktok,pinterest',
    'posting_days': '0,1,2,3,4,5,6',
    'posting_hour': '18',
    'timezone': 'America/New_York',
    'autopilot': '0',
    'base_url': os.getenv('BASE_URL','http://localhost:5000'),
}

def db_conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db_conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)')
        c.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            scheduled_at TEXT,
            title TEXT NOT NULL,
            caption TEXT NOT NULL,
            hook TEXT NOT NULL,
            media_file TEXT,
            platforms TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            external_id TEXT,
            error TEXT
        )''')
        for k,v in DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO settings(k,v) VALUES (?,?)',(k,v))

def get_settings():
    with db_conn() as c:
        rows = c.execute('SELECT k,v FROM settings').fetchall()
    d = DEFAULTS.copy(); d.update({r['k']:r['v'] for r in rows})
    return d

def save_settings(data):
    allowed = set(DEFAULTS)
    with db_conn() as c:
        for k,v in data.items():
            if k in allowed:
                c.execute('INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(k,str(v)))

CONTENT_ANGLES = [
    ('Stop guessing what you have in stock.', 'inventory visibility'),
    ('Your inventory should not live in three notebooks and your memory.', 'organization'),
    ('Know what is selling before you reorder.', 'smarter restocking'),
    ('Small business owners have enough to remember.', 'time savings'),
    ('That “I think I still have two left” feeling has to go.', 'accuracy'),
    ('A simple inventory system can save hours every month.', 'efficiency'),
    ('If stock counts stress you out, simplify the system.', 'pain point'),
    ('Your business deserves better than spreadsheet chaos.', 'simplicity'),
]

def ai_copy(settings):
    key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL','')
    if key and model:
        prompt = f'''Create ONE short social media campaign for {settings['brand_name']}, an inventory app for {settings['audience']}.
Offer: {settings['offer']}
Website: {settings['site_url']}
Return strict JSON with keys: hook, title, caption, visual_text.
Rules: friendly, practical, not hypey; caption 45-90 words; include one clear CTA; no fake statistics; max 4 hashtags; do not mention AI.'''
        try:
            r = requests.post('https://api.openai.com/v1/responses', headers={
                'Authorization': f'Bearer {key}', 'Content-Type':'application/json'
            }, json={'model':model,'input':prompt}, timeout=45)
            r.raise_for_status(); data=r.json()
            text = data.get('output_text')
            if not text:
                parts=[]
                for item in data.get('output',[]):
                    for ct in item.get('content',[]):
                        if ct.get('type') in ('output_text','text'):
                            parts.append(ct.get('text',''))
                text=''.join(parts)
            text=text.strip().removeprefix('```json').removesuffix('```').strip()
            obj=json.loads(text)
            if all(k in obj for k in ('hook','title','caption','visual_text')):
                return obj
        except Exception:
            pass
    hook, angle = random.choice(CONTENT_ANGLES)
    title = random.choice(['Inventory without the headache','Make stock day easier','A simpler way to stay organized','Know what you have'])
    caption = f"{hook} Invome gives small businesses a straightforward place to keep inventory organized, so you can spend less time hunting for counts and more time running your business. Try it free for 7 days, then choose $9.99/month or $99.99/year. {settings['site_url']} #SmallBusiness #InventoryManagement #Invome"
    return {'hook':hook,'title':title,'caption':caption,'visual_text':f"{hook}\n\nTry Invome free for 7 days"}

def font(size=58, bold=False):
    paths=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def fit_text(draw, text, width, start=64, min_size=30, bold=True):
    size=start
    while size>=min_size:
        f=font(size,bold)
        lines=[]
        for para in text.split('\n'):
            if not para: lines.append(''); continue
            words=para.split(); line=''
            for w in words:
                test=(line+' '+w).strip()
                if draw.textbbox((0,0),test,font=f)[2] <= width: line=test
                else:
                    if line: lines.append(line)
                    line=w
            if line: lines.append(line)
        total=len(lines)*(size*1.25)
        if total < 900: return f, lines
        size-=4
    return font(min_size,bold), lines

def make_media(copy, post_id):
    W,H=1080,1920
    img=Image.new('RGB',(W,H),(20,24,32)); d=ImageDraw.Draw(img)
    # card
    d.rounded_rectangle((70,180,1010,1520), radius=46, fill=(245,246,248))
    d.text((120,260),'INVOME',font=font(58,True),fill=(20,24,32))
    f,lines=fit_text(d,copy['visual_text'],760,72,34,True)
    y=470
    for line in lines:
        d.text((120,y),line,font=f,fill=(20,24,32)); y+=int(f.size*1.28)
    d.rounded_rectangle((120,1320,730,1430),radius=28,fill=(20,24,32))
    d.text((165,1350),'invome-560ba.web.app',font=font(36,True),fill=(255,255,255))
    d.text((90,1660),'Inventory made simpler for small business.',font=font(38,False),fill=(238,238,238))
    png=f'post_{post_id}.png'; mp4=f'post_{post_id}.mp4'
    img.save(MEDIA_DIR/png)
    subprocess.run(['ffmpeg','-y','-loop','1','-i',str(MEDIA_DIR/png),'-t','10','-vf',
                    "scale=1080:1920,zoompan=z='min(zoom+0.0006,1.05)':d=250:s=1080x1920:fps=25,format=yuv420p",
                    '-c:v','libx264','-pix_fmt','yuv420p',str(MEDIA_DIR/mp4)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    return mp4

def create_post(scheduled_at=None):
    s=get_settings(); cp=ai_copy(s)
    with db_conn() as c:
        cur=c.execute('INSERT INTO posts(created_at,scheduled_at,title,caption,hook,platforms,status) VALUES (?,?,?,?,?,?,?)',
              (datetime.now(timezone.utc).isoformat(),scheduled_at,cp['title'],cp['caption'],cp['hook'],s['platforms'],'draft'))
        pid=cur.lastrowid
        media=make_media(cp,pid)
        c.execute('UPDATE posts SET media_file=? WHERE id=?',(media,pid))
    return pid

def publish_post(pid):
    s=get_settings(); key=os.getenv('AYRSHARE_API_KEY')
    with db_conn() as c:
        p=c.execute('SELECT * FROM posts WHERE id=?',(pid,)).fetchone()
    if not p: return False,'not found'
    if not key: return False,'AYRSHARE_API_KEY is not configured'
    base=s['base_url'].rstrip('/')
    payload={'post':p['caption'],'platforms':[x.strip() for x in p['platforms'].split(',') if x.strip()],
             'mediaUrls':[f"{base}/media/{p['media_file']}"]}
    profile=os.getenv('AYRSHARE_PROFILE_KEY')
    headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'}
    if profile: headers['Profile-Key']=profile
    try:
        r=requests.post('https://api.ayrshare.com/api/post',headers=headers,json=payload,timeout=60)
        if r.status_code>=400:
            raise RuntimeError(f'{r.status_code}: {r.text[:500]}')
        data=r.json(); ext=data.get('id') or data.get('postIds') or data
        with db_conn() as c:
            c.execute('UPDATE posts SET status=?,external_id=?,error=NULL WHERE id=?',('published',json.dumps(ext),pid))
        return True,data
    except Exception as e:
        with db_conn() as c: c.execute('UPDATE posts SET status=?,error=? WHERE id=?',('failed',str(e),pid))
        return False,str(e)

def autopilot_tick():
    s=get_settings()
    if s.get('autopilot')!='1': return
    now=datetime.now()
    if str(now.weekday()) not in s['posting_days'].split(','): return
    if now.hour != int(s['posting_hour']): return
    # one post per local date
    today=now.date().isoformat()
    with db_conn() as c:
        count=c.execute("SELECT COUNT(*) n FROM posts WHERE substr(created_at,1,10)=? AND status='published'",(today,)).fetchone()['n']
    if count: return
    pid=create_post(); publish_post(pid)

PAGE='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Invome Autopilot</title>
<style>body{font-family:Arial,sans-serif;background:#10141c;color:#f5f7fa;margin:0}.wrap{max-width:1050px;margin:auto;padding:32px}.card{background:#1b2230;border:1px solid #303a4d;border-radius:16px;padding:22px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}input,select{width:100%;box-sizing:border-box;padding:11px;border-radius:9px;border:1px solid #49556c;background:#10141c;color:white}button{padding:11px 16px;border:0;border-radius:9px;font-weight:700;cursor:pointer}.primary{background:white;color:#10141c}.green{background:#4ade80;color:#102016}.muted{color:#aab3c2;font-size:14px}.post{padding:14px;border-top:1px solid #313a4b}.badge{padding:4px 8px;border-radius:20px;background:#303a4d;font-size:12px}a{color:#b9d5ff}</style></head><body><div class=wrap><h1>Invome Content Autopilot</h1><p class=muted>Generate → make media → publish automatically.</p>
<div class=card><h2>Autopilot</h2><form method=post action=/settings><div class=grid>
<label>Website<input name=site_url value="{{s.site_url}}"></label><label>Platforms<input name=platforms value="{{s.platforms}}"></label>
<label>Posting hour (0-23)<input name=posting_hour value="{{s.posting_hour}}"></label><label>Days (Mon=0 … Sun=6)<input name=posting_days value="{{s.posting_days}}"></label>
<label>Public app URL<input name=base_url value="{{s.base_url}}"></label><label>Autopilot<select name=autopilot><option value=0 {% if s.autopilot!='1' %}selected{% endif %}>OFF</option><option value=1 {% if s.autopilot=='1' %}selected{% endif %}>ON</option></select></label></div><br><button class=primary>Save settings</button></form>
<p class=muted>Keys are read from secure environment variables: OPENAI_API_KEY / OPENAI_MODEL and AYRSHARE_API_KEY. A profile key is optional.</p></div>
<div class=card><h2>Run it now</h2><form method=post action=/generate style="display:inline"><button class=primary>Generate post</button></form> <form method=post action=/generate-publish style="display:inline"><button class=green>Generate + Publish</button></form></div>
<div class=card><h2>Recent posts</h2>{% for p in posts %}<div class=post><b>{{p.title}}</b> <span class=badge>{{p.status}}</span><p>{{p.caption}}</p>{% if p.media_file %}<a href="/media/{{p.media_file}}" target=_blank>Preview video</a>{% endif %}{% if p.error %}<p style="color:#fca5a5">{{p.error}}</p>{% endif %}</div>{% else %}<p class=muted>No posts yet.</p>{% endfor %}</div>
</div></body></html>'''

@app.route('/')
def home():
    with db_conn() as c: posts=c.execute('SELECT * FROM posts ORDER BY id DESC LIMIT 20').fetchall()
    return render_template_string(PAGE,s=get_settings(),posts=posts)

@app.post('/settings')
def settings_route():
    save_settings(request.form.to_dict()); return '<script>location.href="/"</script>'

@app.post('/generate')
def generate_route():
    create_post(); return '<script>location.href="/"</script>'

@app.post('/generate-publish')
def generate_publish_route():
    pid=create_post(); publish_post(pid); return '<script>location.href="/"</script>'

@app.post('/api/autopilot/run')
def run_api():
    pid=create_post(); ok,res=publish_post(pid); return jsonify({'ok':ok,'post_id':pid,'result':res})

@app.get('/media/<path:name>')
def media(name): return send_from_directory(MEDIA_DIR,name)

init_db()
sched=BackgroundScheduler(); sched.add_job(autopilot_tick,'interval',minutes=15,max_instances=1); sched.start()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=False)
