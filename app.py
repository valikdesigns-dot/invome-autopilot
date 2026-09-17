import os, json, random, sqlite3, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, send_from_directory, render_template_string
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from apscheduler.schedulers.background import BackgroundScheduler

APP_DIR = Path(__file__).parent
MEDIA_DIR = APP_DIR / 'media'
MEDIA_DIR.mkdir(exist_ok=True)
DB = APP_DIR / 'invome.db'

app = Flask(__name__)

DEFAULTS = {
    'brand_name': 'Invome',
    'site_url': 'https://invomestudio.com',
    'offer': '7-day free trial • $9.99/month or $99.99/year',
    'audience': 'handmade sellers who need to track supplies, calculate real product costs, price confidently, print barcode labels, run checkout, and understand sales',
    'platforms': 'facebook',
    'posting_days': '0,1,2,3,4,5,6',
    'posting_hour': '18',
    'timezone': 'America/New_York',
    'autopilot': '0',
    'publishing_mode': 'test',
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
        c.execute(
            "UPDATE settings SET v=? WHERE k='site_url' AND v=?",
            ('https://invomestudio.com','https://invome-560ba.web.app/start.html'),
        )

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
    ('Stop losing profit to pricing guesswork.', 'When material, packaging, labor, and fees are scattered, it is easy to underprice beautiful work.', 'see your real product costs and choose prices with confidence'),
    ('Know what every handmade product really costs.', 'A finished piece costs more than the most obvious material.', 'bring supplies, labor, packaging, overhead, and selling fees into one clear calculation'),
    ('Create more. Chase supply counts less.', 'Your creative time should not disappear into notebooks and disconnected spreadsheets.', 'keep craft supplies organized without turning inventory into another full-time job'),
    ('Price your handmade work with confidence.', 'Guessing can leave your time unpaid and your profit too thin.', 'build prices from real costs instead of hoping the numbers work'),
    ('Turn supply chaos into a calmer studio.', 'Running out of the right material can stop an order halfway through.', 'track what you use and see what needs attention before it becomes a problem'),
    ('Your craft is creative. Your pricing should be clear.', 'You should not need a maze of spreadsheets to know whether a product is profitable.', 'calculate costs and markups in one practical workflow'),
    ('From raw materials to checkout—in one app.', 'Switching between separate tools creates extra work and missed details.', 'track supplies, price products, print labels, run checkout, and review sales together'),
    ('Protect the profit behind every handmade sale.', 'Small uncounted costs add up across materials, packaging, labor, and fees.', 'account for the details that help turn creative work into a sustainable business'),
]

def ai_copy(settings):
    key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL','')
    if key and model:
        prompt = f'''Create ONE conversion-focused social media campaign for {settings['brand_name']} Studio, a business app for {settings['audience']}.
Offer: {settings['offer']}
Website: {settings['site_url']}
Return strict JSON with keys: hook, title, caption, visual_text.
Rules: write specifically for a handmade maker or craft seller. Lead with a recognizable pain involving supply chaos, hidden material costs, underpricing, labels, checkout, or unclear profit. Show a concrete outcome using only these supported capabilities: track craft supplies, calculate product prices from real costs, print barcode labels, run checkout, and view sales reports. Make the reader picture feeling organized and confident. End with one low-friction CTA to start the free trial. Friendly, specific and practical, never hypey. Caption 55-95 words. No fake statistics, testimonials, urgency or unsupported claims. Max 3 relevant hashtags. Do not mention AI. visual_text must be one punchy benefit-led headline, not a paragraph.'''
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
    hook, pain, outcome = random.choice(CONTENT_ANGLES)
    title = random.choice(['Made for handmade sellers','Know your real costs','Price your craft with confidence','A calmer way to run your studio'])
    caption = (f"{hook} {pain} InvoMe helps you {outcome}. "
               f"Start your 7-day free trial today—no card needed—and see how much clearer your handmade business can feel. "
               f"{settings['site_url']} #HandmadeBusiness #CraftBusiness #InvoMeStudio")
    return {'hook':hook,'title':title,'caption':caption,'visual_text':hook}

def font(size=58, bold=False):
    paths=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def brand_font(size=58):
    p='/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
    return ImageFont.truetype(p,size) if Path(p).exists() else font(size,True)

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

def make_media(copy, post_id, site_url):
    W,H=1080,1920
    bg_path=APP_DIR/'invome-studio-bg.png'
    icon_path=APP_DIR/'invome-icon.png'
    if bg_path.exists():
        bg=Image.open(bg_path).convert('RGB')
        scale=max(W/bg.width,H/bg.height)
        bg=bg.resize((int(bg.width*scale),int(bg.height*scale)),Image.Resampling.LANCZOS)
        left=(bg.width-W)//2; top=(bg.height-H)//2
        img=bg.crop((left,top,left+W,top+H)).convert('RGBA')
    else:
        img=Image.new('RGBA',(W,H),(250,247,244,255))

    # Warm ivory editorial panel with a soft fade into the approved lifestyle photo.
    overlay=Image.new('RGBA',(W,H),(0,0,0,0)); od=ImageDraw.Draw(overlay)
    od.rectangle((0,0,W,770),fill=(252,248,245,246))
    for y in range(770,1030):
        alpha=int(246*(1-(y-770)/260))
        od.line((0,y,W,y),fill=(252,248,245,alpha))
    od.rectangle((0,1510,W,H),fill=(252,248,245,244))
    img=Image.alpha_composite(img,overlay); d=ImageDraw.Draw(img)

    # Exact InvoMe icon and wordmark.
    if icon_path.exists():
        icon=Image.open(icon_path).convert('RGBA')
        # Remove the checkerboard preview background while preserving the mark.
        cleaned=[]
        for r,g,b,a in icon.getdata():
            if min(r,g,b)>185 and max(r,g,b)-min(r,g,b)<10: cleaned.append((r,g,b,0))
            else: cleaned.append((r,g,b,a))
        icon.putdata(cleaned); icon.thumbnail((88,88),Image.Resampling.LANCZOS)
        img.alpha_composite(icon,(68,58))
    d.text((172,72),'InvoMe Studio',font=brand_font(42),fill=(20,16,18,255))
    d.text((70,194),'MADE FOR HANDMADE SELLERS',font=font(25,True),fill=(111,91,103,255))

    # One bold, editorial headline—no fake dashboard or crowded boxes.
    size=78
    while size>=48:
        hf=brand_font(size); lines=[]; line=''
        for word in copy['hook'].split():
            test=(line+' '+word).strip()
            if d.textbbox((0,0),test,font=hf)[2] <= 900: line=test
            else:
                if line: lines.append(line)
                line=word
        if line: lines.append(line)
        if len(lines)<=4: break
        size-=4
    y=250
    for line in lines[:4]:
        d.text((68,y),line,font=hf,fill=(139,43,82,255)); y+=int(size*1.08)
    d.text((70,y+30),'Track supplies. Know your costs. Price with confidence.',font=font(29,True),fill=(18,17,18,255))

    # Simple conversion panel over the lower edge of the photo.
    d.text((70,1560),'YOUR CRAFT IS CREATIVE.',font=font(24,True),fill=(111,91,103,255))
    d.text((70,1600),'Your business numbers can be clear.',font=brand_font(43),fill=(139,43,82,255))
    d.rounded_rectangle((70,1680,570,1765),radius=42,fill=(224,242,241,255),outline=(176,214,211,255),width=2)
    d.text((111,1704),'START YOUR 7-DAY FREE TRIAL',font=font(23,True),fill=(6,94,99,255))
    d.text((612,1707),'NO CARD NEEDED',font=font(22,True),fill=(111,91,103,255))
    display_url=site_url.removeprefix('https://').removeprefix('http://').split('/')[0]
    box=d.textbbox((0,0),display_url,font=font(31,True)); tw=box[2]-box[0]
    d.text(((W-tw)//2,1825),display_url,font=font(31,True),fill=(20,16,18,255))
    png=f'post_{post_id}.png'; mp4=f'post_{post_id}.mp4'
    img.save(MEDIA_DIR/png)
    # Railway's smallest containers cannot safely render a 1080p zoompan animation.
    # A 540x960 H.264 still-video remains vertical and Facebook-compatible while
    # using a fraction of the memory.
    result=subprocess.run([
        'ffmpeg','-y','-framerate','1','-loop','1','-i',str(MEDIA_DIR/png),
        '-t','6','-vf','scale=540:960:flags=lanczos,format=yuv420p',
        '-r','1','-c:v','libx264','-preset','ultrafast','-threads','1',
        '-movflags','+faststart',str(MEDIA_DIR/mp4)
    ],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    if result.returncode:
        raise RuntimeError(f"Video rendering failed: {result.stderr[-500:]}")
    return mp4

def create_post(scheduled_at=None):
    s=get_settings(); cp=ai_copy(s)
    with db_conn() as c:
        cur=c.execute('INSERT INTO posts(created_at,scheduled_at,title,caption,hook,platforms,status) VALUES (?,?,?,?,?,?,?)',
              (datetime.now(timezone.utc).isoformat(),scheduled_at,cp['title'],cp['caption'],cp['hook'],s['platforms'],'draft'))
        pid=cur.lastrowid
    try:
        media=make_media(cp,pid,s['site_url'])
        with db_conn() as c:
            c.execute('UPDATE posts SET media_file=? WHERE id=?',(media,pid))
    except Exception as e:
        with db_conn() as c:
            c.execute('UPDATE posts SET status=?,error=? WHERE id=?',('failed',str(e),pid))
        raise
    return pid

def facebook_config():
    return {
        'token': os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN','').strip(),
        'page_id': os.getenv('FACEBOOK_PAGE_ID','').strip(),
        'api_version': os.getenv('FACEBOOK_GRAPH_API_VERSION','v26.0').strip(),
        'timezone': os.getenv('FACEBOOK_TIMEZONE','America/New_York').strip(),
    }

def facebook_payload(post, live=False, base_url=None):
    media_url=f"{(base_url or get_settings()['base_url']).rstrip('/')}/media/{post['media_file']}"
    return {
        'file_url': media_url,
        'description': post['caption'],
        'published': 'true' if live else 'false',
    }

def page_access_token(cfg):
    """Exchange the configured user/system-user token for this Page's token."""
    root=f"https://graph.facebook.com/{cfg['api_version']}"
    params={'fields':'access_token','access_token':cfg['token']}
    direct=requests.get(f"{root}/{cfg['page_id']}",params=params,timeout=30)
    if direct.ok:
        token=direct.json().get('access_token')
        if token: return token

    # User tokens expose managed Pages through /me/accounts. Keep this fallback
    # so either supported Meta token type works without changing Railway.
    accounts=requests.get(
        f"{root}/me/accounts",
        params={'fields':'id,access_token','access_token':cfg['token']},
        timeout=30,
    )
    if accounts.ok:
        for page in accounts.json().get('data',[]):
            if str(page.get('id')) == str(cfg['page_id']) and page.get('access_token'):
                return page['access_token']
    detail=(direct.text or accounts.text)[:500]
    raise RuntimeError(f'Meta could not provide a Page access token: {detail}')

def publish_post(pid, force_test=False):
    s=get_settings(); cfg=facebook_config()
    if not cfg['token']: return False,'FACEBOOK_PAGE_ACCESS_TOKEN is not configured'
    if not cfg['page_id']: return False,'FACEBOOK_PAGE_ID is not configured'
    with db_conn() as c:
        p=c.execute('SELECT * FROM posts WHERE id=?',(pid,)).fetchone()
    if not p: return False,'not found'
    live=(s.get('publishing_mode')=='live' and not force_test)
    payload=facebook_payload(p,live=live,base_url=s['base_url'])
    try:
        payload['access_token']=page_access_token(cfg)
        url=f"https://graph.facebook.com/{cfg['api_version']}/{cfg['page_id']}/videos"
        r=requests.post(url,data=payload,timeout=90)
        if r.status_code>=400:
            raise RuntimeError(f'{r.status_code}: {r.text[:500]}')
        data=r.json(); ext=data.get('id') or data
        with db_conn() as c:
            now=datetime.now(ZoneInfo(cfg['timezone'])).isoformat()
            c.execute('UPDATE posts SET status=?,scheduled_at=?,external_id=?,error=NULL WHERE id=?',('published' if live else 'facebook_unpublished',now,json.dumps(ext),pid))
        return True,data
    except Exception as e:
        with db_conn() as c: c.execute('UPDATE posts SET status=?,error=? WHERE id=?',('failed',str(e),pid))
        return False,str(e)

def autopilot_tick():
    s=get_settings()
    if s.get('autopilot')!='1' or s.get('publishing_mode')!='live': return
    tz=ZoneInfo(facebook_config()['timezone']); now=datetime.now(tz)
    if str(now.weekday()) not in s['posting_days'].split(','): return
    if now.hour != int(s['posting_hour']): return
    # one post per local date
    today=now.date().isoformat()
    with db_conn() as c:
        count=c.execute("SELECT COUNT(*) n FROM posts WHERE substr(scheduled_at,1,10)=? AND status='published'",(today,)).fetchone()['n']
    if count: return
    pid=create_post(); publish_post(pid)

PAGE='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Invome Autopilot</title>
<style>body{font-family:Arial,sans-serif;background:#10141c;color:#f5f7fa;margin:0}.wrap{max-width:1050px;margin:auto;padding:32px}.card{background:#1b2230;border:1px solid #303a4d;border-radius:16px;padding:22px;margin:18px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}input,select{width:100%;box-sizing:border-box;padding:11px;border-radius:9px;border:1px solid #49556c;background:#10141c;color:white}button{padding:11px 16px;border:0;border-radius:9px;font-weight:700;cursor:pointer}.primary{background:white;color:#10141c}.green{background:#4ade80;color:#102016}.muted{color:#aab3c2;font-size:14px}.post{padding:14px;border-top:1px solid #313a4b}.badge{padding:4px 8px;border-radius:20px;background:#303a4d;font-size:12px}a{color:#b9d5ff}</style></head><body><div class=wrap><h1>Invome Content Autopilot</h1><p class=muted>Generate → make media → publish automatically.</p>
<div class=card><h2>Autopilot</h2><form method=post action=/settings><div class=grid>
<label>Website<input name=site_url value="{{s.site_url}}"></label><label>Destination<input value="InvoMe Facebook Page" disabled></label>
<label>Posting hour (0-23)<input name=posting_hour value="{{s.posting_hour}}"></label><label>Days (Mon=0 … Sun=6)<input name=posting_days value="{{s.posting_days}}"></label>
<label>Public app URL<input name=base_url value="{{s.base_url}}"></label><label>Publishing mode<select name=publishing_mode><option value=test {% if s.publishing_mode!='live' %}selected{% endif %}>TEST — drafts only</option><option value=live {% if s.publishing_mode=='live' %}selected{% endif %}>LIVE — auto-publish</option></select></label>
<label>Autopilot<select name=autopilot><option value=0 {% if s.autopilot!='1' %}selected{% endif %}>OFF</option><option value=1 {% if s.autopilot=='1' %}selected{% endif %}>ON</option></select></label></div><br><button class=primary>Save settings</button></form>
<p class=muted>Facebook credential: <b>{{'configured' if facebook_ready else 'missing'}}</b>. Test mode uploads an unpublished Facebook video and never puts it on the Page timeline. Autopilot only runs when both LIVE and ON.</p></div>
<div class=card><h2>Run it now</h2><form method=post action=/generate style="display:inline"><button class=primary>Generate Draft</button></form> <form method=post action=/generate-test style="display:inline"><button class=green>Send Controlled Unpublished Test</button></form></div>
<div class=card><h2>Recent posts</h2>{% for p in posts %}<div class=post><b>{{p.title}}</b> <span class=badge>{{p.status}}</span><p>{{p.caption}}</p>{% if p.media_file %}<a href="/media/{{p.media_file}}" target=_blank>Preview video</a>{% endif %}{% if p.error %}<p style="color:#fca5a5">{{p.error}}</p>{% endif %}</div>{% else %}<p class=muted>No posts yet.</p>{% endfor %}</div>
</div></body></html>'''

@app.route('/')
def home():
    with db_conn() as c: posts=c.execute('SELECT * FROM posts ORDER BY id DESC LIMIT 20').fetchall()
    cfg=facebook_config()
    return render_template_string(PAGE,s=get_settings(),posts=posts,facebook_ready=bool(cfg['token'] and cfg['page_id']))

@app.post('/settings')
def settings_route():
    save_settings(request.form.to_dict()); return '<script>location.href="/"</script>'

@app.post('/generate')
def generate_route():
    try: create_post()
    except Exception: pass
    return '<script>location.href="/"</script>'

@app.post('/generate-test')
def generate_test_route():
    try:
        pid=create_post(); publish_post(pid,force_test=True)
    except Exception: pass
    return '<script>location.href="/"</script>'

@app.post('/api/autopilot/run')
def run_api():
    s=get_settings()
    if s.get('publishing_mode')!='live' or s.get('autopilot')!='1':
        return jsonify({'ok':False,'error':'Live autopilot is not enabled; use the controlled test route from the dashboard.'}),409
    pid=create_post(); ok,res=publish_post(pid); return jsonify({'ok':ok,'post_id':pid,'result':res})

@app.get('/health')
def health(): return jsonify({'ok':True,'service':'invome-autopilot','publisher':'facebook'})

@app.get('/media/<path:name>')
def media(name): return send_from_directory(MEDIA_DIR,name)

init_db()
sched=BackgroundScheduler(); sched.add_job(autopilot_tick,'interval',minutes=15,max_instances=1); sched.start()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=False)
