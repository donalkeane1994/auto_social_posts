import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

# --------- CONFIG / CONSTANTS ---------
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

LOCAL_XML_DIR = "xml_downloads"
OUT_DIR = "output"
LOGO_PATH = "logo.png"   # logo in repo root

os.makedirs(LOCAL_XML_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

IMG_SIZE = (1080, 1080)
BG_COLOR = (0x1F, 0x2A, 0x4D)     # deep navy #1F2A4D
HEAD_COLOR = (0xFF, 0xBA, 0x00)   # gold/yellow #FFBA00
BODY_COLOR = (255, 255, 255)      # white

# max area for text (reserve space for logo and some margins)
TOP_MARGIN = 220
SIDE_MARGIN = 60
BOTTOM_MARGIN = 60
MAX_TEXT_HEIGHT = IMG_SIZE[1] - TOP_MARGIN - BOTTOM_MARGIN


# --------- FONT HELPERS ---------

def load_font(size, bold=False):
    """
    Try a few common fonts; fall back to default if none found.
    """
    candidates = []
    if bold:
        candidates = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"]
    else:
        candidates = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]

    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    # fall back
    return ImageFont.load_default()


def ordinal(n):
    """1 -> '1st', 2 -> '2nd', etc."""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --------- FTP + XML ---------

def download_all_xml():
    """
    Download all .xml files from the FTP to LOCAL_XML_DIR.
    Returns list of local file paths.
    """
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    names = ftp.nlst()
    xml_files = [n for n in names if n.lower().endswith(".xml")]

    local_paths = []
    for filename in xml_files:
        bio = io.BytesIO()
        print(f"Downloading {filename} from FTP...")
        ftp.retrbinary(f"RETR {filename}", bio.write)
        bio.seek(0)
        local_path = os.path.join(LOCAL_XML_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(bio.read())
        local_paths.append(local_path)

    ftp.quit()
    return local_paths


def load_meeting_date(meeting_elem):
    """
    Meeting date attribute e.g. '29/11/2025' -> datetime.date
    """
    date_str = meeting_elem.attrib.get("date")
    return datetime.strptime(date_str, "%d/%m/%Y").date()


def parse_meeting_data(xml_path, target_date):
    """
    Returns None if meeting is not for target_date.
    Otherwise returns dict with meeting-level data + stats.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    if meeting is None:
        return None

    m_date = load_meeting_date(meeting)
    if m_date != target_date:
        return None

    course_name = meeting.attrib.get("name")
    stats = meeting.find("MiscStatistics")
    if stats is None:
        return None

    topx = stats.find("TopXStatistics")

    def get_top(stat_type, limit=5):
        if topx is None:
            return []
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                return s.findall("Statistic")[:limit]
        return []

    top_track_trainers = get_top("TopTrackTrainers")
    top_track_jockeys = get_top("TopTrackJockeys")
    hot_trainers = get_top("HotTrainers")
    hot_jockeys = get_top("HotJockeys")

    # Dropping in class
    drop_node = stats.find("RunnerDropInClass")
    drop_runners = drop_node.findall("Runner") if drop_node is not None else []

    # Well handicapped
    won_node = stats.find("WonOffHigherHandicap")
    won_runners = won_node.findall("Runner")[:5] if won_node is not None else []

    return {
        "course_name": course_name,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }


# --------- TEXT LAYOUT HELPERS ---------

def build_post1_lines(meeting):
    """Post 1: Top Track Trainers & Jockeys (Last 5 Years)."""
    course = meeting["course_name"]

    lines = []

    # Title
    lines.append({"text": f"{course} - Track Stats", "type": "title"})

    # Trainers
    lines.append({"text": "", "type": "space"})
    lines.append({"text": "Top Track Trainers (Last 5 Years)", "type": "heading"})
    for stat in meeting["top_track_trainers"]:
        rank = stat.attrib.get("rank")
        name = stat.attrib.get("name")
        wins = stat.attrib.get("wins")
        runs = stat.attrib.get("runs")
        sr = stat.attrib.get("strikeRate")
        lines.append({
            "text": f"{ordinal(rank)} {name} {sr}% strike rate ({wins} wins from {runs} runners)",
            "type": "body"
        })

    # Jockeys
    lines.append({"text": "", "type": "space"})
    lines.append({"text": "Top Track Jockeys (Last 5 Years)", "type": "heading"})
    for stat in meeting["top_track_jockeys"]:
        rank = stat.attrib.get("rank")
        name = stat.attrib.get("name")
        wins = stat.attrib.get("wins")
        runs = stat.attrib.get("runs")
        sr = stat.attrib.get("strikeRate")
        lines.append({
            "text": f"{ordinal(rank)} {name} {sr}% strike rate ({wins} wins from {runs} rides)",
            "type": "body"
        })

    return lines


def build_post2_lines(meeting):
    """Post 2: Hot Trainers & Hot Jockeys (Last Month)."""
    course = meeting["course_name"]

    lines = []
    lines.append({"text": f"{course} - Hot Form", "type": "title"})

    lines.append({"text": "", "type": "space"})
    lines.append({"text": "Hot Trainers (Last Month)", "type": "heading"})
    for stat in meeting["hot_trainers"]:
        rank = stat.attrib.get("rank")
        name = stat.attrib.get("name")
        wins = stat.attrib.get("wins")
        runs = stat.attrib.get("runs")
        sr = stat.attrib.get("strikeRate")
        lines.append({
            "text": f"{ordinal(rank)} {name} {sr}% strike rate ({wins} wins from {runs} runners)",
            "type": "body"
        })

    lines.append({"text": "", "type": "space"})
    lines.append({"text": "Hot Jockeys (Last Month)", "type": "heading"})
    for stat in meeting["hot_jockeys"]:
        rank = stat.attrib.get("rank")
        name = stat.attrib.get("name")
        wins = stat.attrib.get("wins")
        runs = stat.attrib.get("runs")
        sr = stat.attrib.get("strikeRate")
        lines.append({
            "text": f"{ordinal(rank)} {name} {sr}% strike rate ({wins} wins from {runs} rides)",
            "type": "body"
        })

    return lines


def build_post3_lines(meeting):
    """Post 3: Dropping in Class & Well Handicapped."""
    course = meeting["course_name"]

    lines = []
    lines.append({"text": f"{course} - Handicapping Angles", "type": "title"})

    # Dropping in class
    lines.append({"text": "", "type": "space"})
    lines.append({"text": f"Today's Runners Dropping in Class", "type": "heading"})
    if meeting["drop_runners"]:
        for r in meeting["drop_runners"]:
            name = r.attrib.get("name")
            time = r.attrib.get("raceTime")
            lines.append({
                "text": f"{name} runs in the {time}",
                "type": "body"
            })
    else:
        lines.append({"text": "None today.", "type": "body"})

    # Well handicapped
    lines.append({"text": "", "type": "space"})
    lines.append({"text": f"Well Handicapped Runners Today", "type": "heading"})
    if meeting["won_runners"]:
        for r in meeting["won_runners"]:
            name = r.attrib.get("name")
            time = r.attrib.get("raceTime")
            w_node = r.find("Weight")
            if w_node is not None:
                try:
                    wt_then = int(w_node.attrib.get("weightThen"))
                    wt_now = int(w_node.attrib.get("weightNow"))
                    diff = wt_then - wt_now
                    diff_str = f"{diff}lb" if diff > 0 else "same mark"
                except Exception:
                    diff_str = "higher mark"
            else:
                diff_str = "higher mark"

            lines.append({
                "text": f"{name} won off a higher mark – runs in the {time} today ({diff_str})",
                "type": "body"
            })
    else:
        lines.append({"text": "None today.", "type": "body"})

    return lines


def measure_and_scale_lines(lines):
    """
    Decide font sizes (title/heading/body) & spacing so that
    text fits vertically in MAX_TEXT_HEIGHT.
    """
    # Base sizes
    base_sizes = {
        "title": 58,
        "heading": 38,
        "body": 32
    }
    # Base spacing
    base_spacing = 10  # extra pixels between lines

    # dummy image/draw for measurement
    dummy_img = Image.new("RGB", IMG_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(dummy_img)

    scale = 1.0
    min_scale = 0.6

    def total_height_for_scale(s):
        total_h = 0
        for line in lines:
            if line["type"] == "space":
                total_h += int(base_spacing * s * 1.5)
                continue
            size = int(base_sizes.get(line["type"], base_sizes["body"]) * s)
            font = load_font(size, bold=(line["type"] in ["title", "heading"]))
            _, h = draw.textsize(line["text"], font=font)
            total_h += h + int(base_spacing * s)
        return total_h

    while True:
        h = total_height_for_scale(scale)
        if h <= MAX_TEXT_HEIGHT or scale <= min_scale:
            break
        scale -= 0.05

    # Now compute actual sizes / fonts
    fonts = {}
    for t in ["title", "heading", "body"]:
        size = int(base_sizes[t] * scale)
        fonts[t] = load_font(size, bold=(t in ["title", "heading"]))

    line_spacing = int(base_spacing * scale)

    return fonts, line_spacing


def render_post_image(lines, outfile):
    """
    Renders one image with:
    - background color
    - large logo top-left
    - all text with automatic font scaling
    """
    img = Image.new("RGB", IMG_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Place logo
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            # target height ~ 180px for good visibility
            target_h = 180
            ratio = target_h / float(logo.height)
            target_w = int(logo.width * ratio)
            logo = logo.resize((target_w, target_h), Image.LANCZOS)
            img.paste(logo, (SIDE_MARGIN, 30), logo)
        except Exception as e:
            print("Logo load error:", e)

    # Determine fonts and spacing to fit text
    fonts, line_spacing = measure_and_scale_lines(lines)
    y = TOP_MARGIN

    for line in lines:
        if line["type"] == "space":
            y += int(line_spacing * 1.5)
            continue

        text = line["text"]
        if not text:
            y += line_spacing
            continue

        font = fonts.get(line["type"], fonts["body"])
        color = BODY_COLOR
        if line["type"] in ["title", "heading"]:
            color = HEAD_COLOR

        # left aligned text
        draw.text(
            (SIDE_MARGIN, y),
            text,
            font=font,
            fill=color
        )
        _, h = draw.textsize(text, font=font)
        y += h + line_spacing

    img.save(outfile)
    print("Saved image:", outfile)
    return outfile


# --------- EMAIL ---------

def send_email_with_attachments(attachments):
    if not attachments:
        print("No attachments to email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached.")

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="image",
            subtype="png",
            filename=os.path.basename(path),
        )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print(f"Email sent with {len(attachments)} attachments.")


# --------- MAIN FLOW ---------

def main():
    # target date = tomorrow (you’re running this at 10:00 each day)
    today_utc = datetime.utcnow().date()
    target_date = today_utc + timedelta(days=1)
    print("Target meeting date:", target_date)

    xml_paths = download_all_xml()
    print("Downloaded XML files:", xml_paths)

    all_attachments = []

    for xml_path in xml_paths:
        print("Parsing", xml_path)
        meeting = parse_meeting_data(xml_path, target_date)
        if not meeting:
            continue

        course_slug = meeting["course_name"].replace(" ", "_")

        # Post 1 – Top track
        lines1 = build_post1_lines(meeting)
        out1 = os.path.join(OUT_DIR, f"{course_slug}_post1.png")
        render_post_image(lines1, out1)
        all_attachments.append(out1)

        # Post 2 – Hot form
        lines2 = build_post2_lines(meeting)
        out2 = os.path.join(OUT_DIR, f"{course_slug}_post2.png")
        render_post_image(lines2, out2)
        all_attachments.append(out2)

        # Post 3 – Handicapping angles
        lines3 = build_post3_lines(meeting)
        out3 = os.path.join(OUT_DIR, f"{course_slug}_post3.png")
        render_post_image(lines3, out3)
        all_attachments.append(out3)

    send_email_with_attachments(all_attachments)


if __name__ == "__main__":
    main()
