{\rtf1\ansi\ansicpg1252\cocoartf2821
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # autopost.py\
# Requires: Python 3.9+, packages: pillow, requests\
# Usage: python autopost.py\
import os\
import ftplib\
import io\
import xml.etree.ElementTree as ET\
from PIL import Image, ImageDraw, ImageFont\
import requests\
import base64\
import subprocess\
\
# ---------- Config (reads from env / Secrets) ----------\
FTP_SERVER = os.environ.get("FTP_SERVER")\
FTP_USER   = os.environ.get("FTP_USER")\
FTP_PASS   = os.environ.get("FTP_PASS")\
\
FB_APP_ID = os.environ.get("FB_APP_ID")\
FB_APP_SECRET = os.environ.get("FB_APP_SECRET")\
FB_USER_ACCESS_TOKEN = os.environ.get("FB_USER_ACCESS_TOKEN")\
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")\
IG_USER_ID = os.environ.get("IG_USER_ID")  # instagram business id\
\
# Filepaths\
LOCAL_XML = "meeting.xml"\
OUT_DIR = "output"\
os.makedirs(OUT_DIR, exist_ok=True)\
\
# ---------- Helper: download XML from FTP ----------\
def download_xml_via_ftp(ftp_server, user, pw, remote_path_glob="*.xml"):\
    # connect and find most recent xml by listing (here we use explicit filename if known)\
    ftp = ftplib.FTP(ftp_server)\
    ftp.login(user, pw)\
    # if you know filename, replace the following with ftp.retrbinary for that file\
    # For safety, try to download the only XML in root or a known path\
    names = ftp.nlst()\
    xml_files = [n for n in names if n.lower().endswith(".xml")]\
    if not xml_files:\
        raise RuntimeError("No XML found on FTP root; adapt path.")\
    filename = xml_files[0]\
    print("Downloading", filename)\
    bio = io.BytesIO()\
    ftp.retrbinary(f"RETR \{filename\}", bio.write)\
    ftp.quit()\
    bio.seek(0)\
    with open(LOCAL_XML, "wb") as f:\
        f.write(bio.read())\
    return LOCAL_XML\
\
# ---------- Parse XML (the exact tags you requested) ----------\
def parse_meeting_xml(xml_path):\
    tree = ET.parse(xml_path)\
    root = tree.getroot()\
    meeting = root.find("Meeting")\
    stats = meeting.find("MiscStatistics")\
    topx = stats.find("TopXStatistics")\
\
    def get_top5(stat_type):\
        node = None\
        for s in topx.findall("TopXStatistic"):\
            if s.attrib.get("statisticType") == stat_type:\
                node = s\
                break\
        items = []\
        if node is not None:\
            for stat in node.findall("Statistic")[:5]:\
                items.append(\{\
                    "rank": stat.attrib.get("rank"),\
                    "name": stat.attrib.get("name"),\
                    "wins": stat.attrib.get("wins"),\
                    "runs": stat.attrib.get("runs"),\
                    "strikeRate": stat.attrib.get("strikeRate")\
                \})\
        return items\
\
    top_track_jockeys = get_top5("TopTrackJockeys")\
    hot_jockeys = get_top5("HotJockeys")\
    top_track_trainers = get_top5("TopTrackTrainers")\
    hot_trainers = get_top5("HotTrainers")\
\
    # Runner lists\
    drop_nodes = stats.find("RunnerDropInClass")\
    drop_runners = []\
    if drop_nodes is not None:\
        for r in drop_nodes.findall("Runner"):\
            drop_runners.append(\{\
                "name": r.attrib.get("name"),\
                "raceTime": r.attrib.get("raceTime"),\
                "trainer": r.find("Trainer").attrib.get("name") if r.find("Trainer") is not None else "",\
                "jockey": r.find("Jockey").attrib.get("name") if r.find("Jockey") is not None else "",\
                "classDiff": r.find("ClassDifference").attrib.get("value") if r.find("ClassDifference") is not None else ""\
            \})\
\
    won_nodes = stats.find("WonOffHigherHandicap")\
    won_runners = []\
    if won_nodes is not None:\
        for r in won_nodes.findall("Runner")[:5]:  # cap at first 5\
            won_runners.append(\{\
                "name": r.attrib.get("name"),\
                "raceTime": r.attrib.get("raceTime"),\
                "trainer": r.find("Trainer").attrib.get("name") if r.find("Trainer") is not None else "",\
                "jockey": r.find("Jockey").attrib.get("name") if r.find("Jockey") is not None else "",\
                "weightThen": r.find("Weight").attrib.get("weightThen") if r.find("Weight") is not None else "",\
                "weightNow": r.find("Weight").attrib.get("weightNow") if r.find("Weight") is not None else ""\
            \})\
\
    return \{\
        "top_track_jockeys": top_track_jockeys,\
        "hot_jockeys": hot_jockeys,\
        "top_track_trainers": top_track_trainers,\
        "hot_trainers": hot_trainers,\
        "drop_runners": drop_runners,\
        "won_runners": won_runners\
    \}\
\
# ---------- Simple template rendering with Pillow ----------\
def render_post1(data, outpath="output/post1.png", site_primary="#0b3d2e", logo_path="assets/logo.png"):\
    # Image size 1080x1080 (IG square)\
    W, H = 1080, 1080\
    im = Image.new("RGBA", (W, H), (255,255,255,255))\
    draw = ImageDraw.Draw(im)\
    # fonts (system fallback)\
    try:\
        font_h = ImageFont.truetype("arialbd.ttf", 48)\
        font_s = ImageFont.truetype("arial.ttf", 30)\
    except:\
        font_h = ImageFont.load_default()\
        font_s = ImageFont.load_default()\
    padding = 40\
    draw.text((padding, padding), "Top Jockeys & Trainers", font=font_h, fill=site_primary)\
    y = padding + 80\
\
    def draw_list(title, items, x):\
        nonlocal y\
        draw.text((x, y), title, font=font_s, fill=(30,30,30))\
        yy = y + 30\
        for it in items:\
            line = f"\{it.get('rank')\}. \{it.get('name')\} (\{it.get('wins')\}/\{it.get('runs')\})"\
            draw.text((x, yy), line, font=font_s, fill=(60,60,60))\
            yy += 28\
        return yy + 10\
\
    # left column\
    left_x = padding\
    y_left = y\
    y_left = draw_list("Top Track Jockeys", data["top_track_jockeys"], left_x)\
    y_left = draw_list("Hot Jockeys", data["hot_jockeys"], left_x)\
\
    # right column\
    right_x = W//2 + 20\
    y_right = y\
    y_right = draw_list("Top Track Trainers", data["top_track_trainers"], right_x)\
    y_right = draw_list("Hot Trainers", data["hot_trainers"], right_x)\
\
    # place logo if exists\
    if os.path.exists(logo_path):\
        logo = Image.open(logo_path).convert("RGBA")\
        logo.thumbnail((160,160))\
        im.paste(logo, (W-180, H-180), logo)\
\
    im.save(outpath)\
    print("Saved", outpath)\
    return outpath\
\
def render_post2(data, outpath="output/post2.png", site_primary="#0b3d2e", logo_path="assets/logo.png"):\
    W, H = 1080, 1080\
    im = Image.new("RGBA", (W, H), (255,255,255,255))\
    draw = ImageDraw.Draw(im)\
    try:\
        font_h = ImageFont.truetype("arialbd.ttf", 48)\
        font_s = ImageFont.truetype("arial.ttf", 30)\
    except:\
        font_h = ImageFont.load_default()\
        font_s = ImageFont.load_default()\
    padding = 40\
    draw.text((padding, padding), "Dropping & Well handicapped", font=font_h, fill=site_primary)\
    y = padding + 80\
    draw.text((padding, y), "Horses dropping in class today:", font=font_s, fill=(30,30,30))\
    y += 36\
    for r in data["drop_runners"][:10]:\
        draw.text((padding, y), f"\'95 \{r['name']\} (\{r['raceTime']\}) - \{r['classDiff']\} \uc0\u8595 ", font=font_s, fill=(60,60,60))\
        y += 28\
        if y > H - 200: break\
\
    y2 = H//2 + 10\
    draw.text((padding, y2), "Well handicapped (won off higher handicap):", font=font_s, fill=(30,30,30))\
    y2 += 36\
    for r in data["won_runners"][:5]:\
        draw.text((padding, y2), f"\'95 \{r['name']\} (was \{r['weightThen']\} \uc0\u8594  now \{r['weightNow']\})", font=font_s, fill=(60,60,60))\
        y2 += 28\
\
    # logo\
    if os.path.exists(logo_path):\
        logo = Image.open(logo_path).convert("RGBA")\
        logo.thumbnail((160,160))\
        im.paste(logo, (W-180, H-180), logo)\
\
    im.save(outpath)\
    print("Saved", outpath)\
    return outpath\
\
# ---------- Post to Facebook Page (photo upload) ----------\
def post_image_to_facebook(page_id, page_token, image_path, message):\
    url = f"https://graph.facebook.com/v15.0/\{page_id\}/photos"\
    files = \{"source": open(image_path, "rb")\}\
    data = \{"caption": message, "access_token": page_token\}\
    r = requests.post(url, files=files, data=data)\
    print("FB upload response:", r.status_code, r.text)\
    return r.json()\
\
# ---------- Instagram publish (requires image URL) ----------\
def publish_to_instagram(ig_user_id, image_url, caption, access_token):\
    # Step 1: create media object\
    create_url = f"https://graph.facebook.com/v15.0/\{ig_user_id\}/media"\
    payload = \{\
        "image_url": image_url,\
        "caption": caption,\
        "access_token": access_token\
    \}\
    r = requests.post(create_url, data=payload)\
    print("IG create media:", r.status_code, r.text)\
    if r.status_code != 200:\
        return r.json()\
    creation_id = r.json().get("id")\
    # Step 2: publish\
    publish_url = f"https://graph.facebook.com/v15.0/\{ig_user_id\}/media_publish"\
    r2 = requests.post(publish_url, data=\{"creation_id": creation_id, "access_token": access_token\})\
    print("IG publish:", r2.status_code, r2.text)\
    return r2.json()\
\
# ---------- Main flow ----------\
def main():\
    # 1) get xml from FTP\
    try:\
        xml_path = download_xml_via_ftp(FTP_SERVER, FTP_USER, FTP_PASS)\
    except Exception as e:\
        print("FTP fail:", e)\
        # fallback: use meeting.xml if already in repo\
        xml_path = LOCAL_XML if os.path.exists(LOCAL_XML) else None\
        if not xml_path:\
            raise\
\
    data = parse_meeting_xml(xml_path)\
    # show parsed sample\
    print("Parsed:", \{k: len(v) for k,v in data.items()\})\
\
    # render images\
    p1 = render_post1(data, outpath=os.path.join(OUT_DIR, "post1.png"))\
    p2 = render_post2(data, outpath=os.path.join(OUT_DIR, "post2.png"))\
\
    # Publish to Facebook (uses page access token)\
    # You should obtain a Page Access token via FB API call:\
    page_token = FB_USER_ACCESS_TOKEN  # for simplicity; ideally exchange for page token\
    caption1 = "Top Jockeys & Trainers \'97 "  # build nice caption from data if desired\
    fb_res1 = post_image_to_facebook(FB_PAGE_ID, page_token, p1, caption1)\
    fb_res2 = post_image_to_facebook(FB_PAGE_ID, page_token, p2, caption1)\
\
    # For Instagram: needs image_url (public). You can:\
    # - Commit images to gh-pages branch and use raw.githubusercontent URL,\
    # - Or upload to a public hosting and use that URL.\
    # Here we assume you will push them to gh-pages and construct the raw URL:\
    # raw_url = f"https://raw.githubusercontent.com/<USER>/<REPO>/gh-pages/\{OUT_DIR\}/post1.png"\
    # For demo:\
    # raw_url = os.environ.get("PUBLIC_IMAGE_URL_POST1")\
    raw_url = os.environ.get("PUBLIC_IMAGE_URL_POST1")\
    if raw_url and IG_USER_ID:\
        ig_res1 = publish_to_instagram(IG_USER_ID, raw_url, caption1, FB_USER_ACCESS_TOKEN)\
        print("IG result:", ig_res1)\
    else:\
        print("IG publish skipped: PUBLIC_IMAGE_URL_POST1 or IG_USER_ID missing.")\
\
if __name__ == "__main__":\
    main()\
}