import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

# ------------ CONFIG ----------------
BACKGROUND = "#1F2A4D"
HEADING_COLOR = "#FFBA00"
BODY_COLOR = "#FFFFFF"

WIDTH = 1080
HEIGHT = 1350        # More vertical room
MARGIN = 60
LINE_SPACING = 12    # extra spacing
SECTION_SPACING = 40 # extra spacing
TITLE_SPACING = 60
LOGO_SIZE = 220       # bigger logo

FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

# ------------ FONTS -----------------
def load_font(size):
    """Always fall back safely on GitHub Actions."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

TITLE_FONT = load_font(70)
SUBTITLE_FONT = load_font(50)
BODY_FONT = load_font(42)

# ------------ TEXT HELPERS -----------------
def wrap_text(draw, text, font, max_width):
    """Wrap text to fit image width."""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        test = (current + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines

def draw_block(draw, x, y, text, font, fill, max_width):
    """Draw wrapped text block, return new y position."""
    lines = wrap_text(draw, text, font, max_width)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + LINE_SPACING
    return y

# ------------ FTP DOWNLOAD -----------------
def download_todays_files():
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)

    files = ftp.nlst()
    today = get_tomorrow_tla_date()  # Adjusted logic for 10 AM UK run

    todays_files = [f for f in files if f.endswith(today + ".xml")]
    ftp_results = []

    for fname in todays_files:
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {fname}", bio.write)
        local = f"{OUT_DIR}/{fname}"
        with open(local, "wb") as out:
            out.write(bio.getvalue())
        ftp_results.append(local)

    ftp.quit()
    return ftp_results

# ------------ DATE LOGIC -----------------
import datetime

def get_tomorrow_tla_date():
    """Return 4-digit datestring for tomorrow: DDMM"""
    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
    return tomorrow.strftime("%d%m")

# ------------ XML PARSING -----------------
def parse_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    meeting = root.find("Meeting")
    course_name = meeting.attrib["name"]

    stats = meeting.find("MiscStatistics")
    topx = stats.find("TopXStatistics")

    def get_stats(tag):
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == tag:
                return s.findall("Statistic")[:5]
        return []

    # Data groups
    top_track_j = get_stats("TopTrackJockeys")
    top_track_t = get_stats("TopTrackTrainers")

    hot_j = get_stats("HotJockeys")
    hot_t = get_stats("HotTrainers")

    drop_nodes = stats.find("RunnerDropInClass")
    drop = drop_nodes.findall("Runner") if drop_nodes is not None else []

    won_nodes = stats.find("WonOffHigherHandicap")
    won = won_nodes.findall("Runner")[:5] if won_nodes is not None else []

    return {
        "course": course_name,
        "top_track_j": top_track_j,
        "top_track_t": top_track_t,
        "hot_j": hot_j,
        "hot_t": hot_t,
        "drop": drop,
        "won": won,
    }

# ------------ IMAGE GENERATION -----------------
def load_logo():
    """Load logo.png from root directory (because GitHub upload issue)."""
    try:
        logo = Image.open("logo.png").convert("RGBA")
        logo = logo.resize((LOGO_SIZE, LOGO_SIZE))
        return logo
    except:
        return None

LOGO = load_logo()

def create_canvas():
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(img)
    return img, draw

# --- POST 1 ---
def render_post1(data):
    img, draw = create_canvas()
    y = MARGIN

    # Logo
    if LOGO:
        img.paste(LOGO, (MARGIN, y), LOGO)
    y += LOGO_SIZE + 40

    max_w = WIDTH - MARGIN*2

    # Heading
    title = f"Top Track Trainers & Jockeys\n{data['course']} - Last 5 Years"
    y = draw_block(draw, MARGIN, y, title, TITLE_FONT, HEADING_COLOR, max_w)
    y += TITLE_SPACING

    # Trainers
    y = draw_block(draw, MARGIN, y, "Top Track Trainers", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for s in data["top_track_t"]:
        txt = f"{s.attrib['rank']}st  {s.attrib['name']}  {s.attrib['strikeRate']}% ({s.attrib['wins']} wins / {s.attrib['runs']})"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)
    y += SECTION_SPACING

    # Jockeys
    y = draw_block(draw, MARGIN, y, "Top Track Jockeys", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for s in data["top_track_j"]:
        txt = f"{s.attrib['rank']}st  {s.attrib['name']}  {s.attrib['strikeRate']}% ({s.attrib['wins']} wins / {s.attrib['runs']})"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)

    out = f"{OUT_DIR}/post1_{data['course']}.png"
    img.save(out)
    return out

# --- POST 2 ---
def render_post2(data):
    img, draw = create_canvas()
    y = MARGIN

    if LOGO:
        img.paste(LOGO, (MARGIN, y), LOGO)
    y += LOGO_SIZE + 40

    max_w = WIDTH - MARGIN*2

    title = f"Hot Trainers & Jockeys\n{data['course']} (Last Month)"
    y = draw_block(draw, MARGIN, y, title, TITLE_FONT, HEADING_COLOR, max_w)
    y += TITLE_SPACING

    # Hot Trainers
    y = draw_block(draw, MARGIN, y, "Hot Trainers", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for s in data["hot_t"]:
        txt = f"{s.attrib['rank']}st  {s.attrib['name']}  {s.attrib['strikeRate']}% ({s.attrib['wins']} wins / {s.attrib['runs']})"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)
    y += SECTION_SPACING

    # Hot Jockeys
    y = draw_block(draw, MARGIN, y, "Hot Jockeys", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for s in data["hot_j"]:
        txt = f"{s.attrib['rank']}st  {s.attrib['name']}  {s.attrib['strikeRate']}% ({s.attrib['wins']} wins / {s.attrib['runs']})"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)

    out = f"{OUT_DIR}/post2_{data['course']}.png"
    img.save(out)
    return out

# --- POST 3 ---
def render_post3(data):
    img, draw = create_canvas()
    y = MARGIN

    if LOGO:
        img.paste(LOGO, (MARGIN, y), LOGO)
    y += LOGO_SIZE + 40

    max_w = WIDTH - MARGIN*2

    title = f"Today's Horses - {data['course']}"
    y = draw_block(draw, MARGIN, y, title, TITLE_FONT, HEADING_COLOR, max_w)
    y += TITLE_SPACING

    # Dropping in Class
    y = draw_block(draw, MARGIN, y, "Dropping in Class", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for r in data["drop"]:
        txt = f"{r.attrib['name']} running in the {r.attrib['raceTime']}"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)
    y += SECTION_SPACING

    # Well Handicapped
    y = draw_block(draw, MARGIN, y, "Well Handicapped", SUBTITLE_FONT, HEADING_COLOR, max_w)
    for r in data["won"]:
        w = r.find("Weight")
        diff = int(w.attrib["weightThen"]) - int(w.attrib["weightNow"])
        txt = f"{r.attrib['name']} won off a {diff} lb higher mark – runs in the {r.attrib['raceTime']}"
        y = draw_block(draw, MARGIN, y, txt, BODY_FONT, BODY_COLOR, max_w)

    out = f"{OUT_DIR}/post3_{data['course']}.png"
    img.save(out)
    return out

# ------------ EMAIL SENDING -----------------
def send_email(attachments):
    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached.")

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="image", subtype="png", filename=os.path.basename(path))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

# ------------ MAIN -----------------
def main():
    xml_files = download_todays_files()
    attachments = []

    for file in xml_files:
        data = parse_xml(file)
        attachments.append(render_post1(data))
        attachments.append(render_post2(data))
        attachments.append(render_post3(data))

    send_email(attachments)
    print("Email sent!")

if __name__ == "__main__":
    main()
