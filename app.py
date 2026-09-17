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
    'audience': 'small business owners who need a simpler way to track inventory',
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
    ('Know what is running low before a customer asks.', 'Last-minute stock checks steal time and make every sale harder.', 'see what needs attention and act before low stock becomes a missed sale'),
    ('Stop relying on memory to run your inventory.', 'Notebook counts and scattered lists get outdated fast.', 'keep your stock information organized in one straightforward place'),
    ('Spend less time counting. Spend more time growing.', 'Inventory admin should not consume the hours you need for customers.', 'stay on top of everyday stock without turning it into a second job'),
    ('Make confident restocking decisions.', 'Guessing what to reorder can tie up money in the wrong products.', 'understand what you have before you spend on more inventory'),
    ('Turn “I think we have it” into “Yes, we do.”', 'Customers expect a clear answer when they ask what is available.', 'check stock with confidence and give customers a better experience'),
    ('Your inventory can feel under control again.', 'Growing product lists become stressful when the system cannot keep up.', 'build a simpler routine that is easier to maintain as your business grows'),
    ('Catch low stock before it costs you a sale.', 'A popular item can disappear faster than expected.', 'spot items that need attention while there is still time to reorder'),
    ('Replace inventory chaos with one clear view.', 'Multiple spreadsheets and handwritten notes create duplicate work.', 'bring everyday inventory tracking into one clean, accessible workflow'),
]

def ai_copy(settings):
    key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL','')
    if key and model:
        prompt = f'''Create ONE conversion-focused social media campaign for {settings['brand_name']}, an inventory app for {settings['audience']}.
Offer: {settings['offer']}
Website: {settings['site_url']}
Return strict JSON with keys: hook, title, caption, visual_text.
Rules: lead with a recognizable inventory pain; show a concrete day-to-day outcome; make the reader picture the relief or confidence they gain; end with one low-friction CTA to start the free trial. Friendly, specific and practical, never hypey. Caption 55-95 words. No fake statistics, testimonials, urgency or unsupported feature claims. Max 3 relevant hashtags. Do not mention AI. visual_text must be one punchy benefit-led headline, not a paragraph.'''
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
    title = random.choice(['Inventory with less guesswork','A clearer way to manage stock','Know what needs attention','Make inventory feel manageable'])
    caption = (f"{hook} {pain} InvoMe helps you {outcome}. "
               f"Start your 7-day free trial today and see how much simpler your inventory routine can feel. "
               f"{settings['site_url']} #SmallBusiness #InventoryManagement #InvoMe")
    return {'hook':hook,'title':title,'caption':caption,'visual_text':hook}

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

def make_media(copy, post_id, site_url):
    W,H=1080,1920
    # Deep navy-to-indigo brand gradient.
    img=Image.new('RGB',(W,H)); d=ImageDraw.Draw(img)
    top=(12,22,48); bottom=(42,30,92)
    for y in range(H):
        t=y/(H-1)
        color=tuple(int(top[i]*(1-t)+bottom[i]*t) for i in range(3))
        d.line((0,y,W,y),fill=color)

    # Soft dimensional background accents.
    glow=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((650,-170,1250,430),fill=(74,222,180,70))
    gd.ellipse((-300,1180,500,1980),fill=(104,92,255,65))
    glow=glow.filter(ImageFilter.GaussianBlur(80)); img=Image.alpha_composite(img.convert('RGBA'),glow)
    d=ImageDraw.Draw(img)
    for x,y,r in [(95,380,7),(960,520,5),(875,1420,8),(150,1580,5)]:
        d.ellipse((x-r,y-r,x+r,y+r),fill=(255,255,255,100))

    # Brand header and category pill.
    d.rounded_rectangle((70,82,330,164),radius=41,fill=(255,255,255,24),outline=(255,255,255,70),width=2)
    d.ellipse((94,106,140,152),fill=(71,224,174,255))
    d.text((158,103),'INVOME',font=font(38,True),fill='white')
    d.rounded_rectangle((720,94,1008,154),radius=30,fill=(71,224,174,255))
    d.text((763,109),'SMALL BUSINESS',font=font(24,True),fill=(9,31,42,255))

    # Strong headline hierarchy.
    d.text((72,238),copy['title'].upper(),font=font(27,True),fill=(110,236,198,255))
    f,lines=fit_text(d,copy['hook'],900,76,44,True)
    y=300
    for line in lines[:4]:
        d.text((70,y),line,font=f,fill='white'); y+=int(f.size*1.16)

    # Product-style inventory dashboard card with shadow.
    card=(72,720,1008,1390)
    shadow=Image.new('RGBA',(W,H),(0,0,0,0)); sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((card[0]+16,card[1]+22,card[2]+16,card[3]+22),radius=48,fill=(0,0,0,105))
    shadow=shadow.filter(ImageFilter.GaussianBlur(24)); img=Image.alpha_composite(img,shadow); d=ImageDraw.Draw(img)
    d.rounded_rectangle(card,radius=48,fill=(247,249,252,255))
    d.text((122,775),'Inventory overview',font=font(39,True),fill=(20,30,50,255))
    d.text((122,830),'Everything important, at a glance.',font=font(27),fill=(91,102,122,255))
    d.rounded_rectangle((770,773,948,836),radius=30,fill=(224,250,241,255))
    d.text((806,790),'LIVE VIEW',font=font(23,True),fill=(16,126,92,255))

    rows=[('Stock at a glance','Know what you have',(71,224,174,255)),('Items needing attention','Act before stock runs out',(255,184,76,255)),('One clear workflow','Less hunting. Less guesswork.',(115,110,255,255))]
    ry=910
    for label,value,color in rows:
        d.rounded_rectangle((118,ry,962,ry+112),radius=25,fill=(233,238,246,255))
        d.rounded_rectangle((142,ry+25,204,ry+87),radius=18,fill=color)
        d.text((232,ry+19),label,font=font(29,True),fill=(28,38,58,255))
        d.text((232,ry+61),value,font=font(25),fill=(94,105,124,255))
        d.text((900,ry+35),'›',font=font(42,True),fill=(115,124,143,255))
        ry+=132

    # Benefit strip and high-contrast CTA.
    d.text((72,1474),'TRACK STOCK   •   SPOT TRENDS   •   REORDER SMARTER',font=font(25,True),fill=(205,211,230,255))
    d.rounded_rectangle((70,1548,1010,1715),radius=42,fill=(71,224,174,255))
    d.text((118,1587),'Try InvoMe free for 7 days',font=font(44,True),fill=(9,31,42,255))
    d.text((118,1650),'Simple setup. Clear inventory. Less guesswork.',font=font(25),fill=(25,70,68,255))
    display_url=site_url.removeprefix('https://').removeprefix('http://').split('/')[0]
    box=d.textbbox((0,0),display_url,font=font(33,True)); tw=box[2]-box[0]
    d.text(((W-tw)//2,1780),display_url,font=font(33,True),fill='white')
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
