import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------
# CONFIG / CONSTANTS
# --------------------------------------------------------------------
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

# Directories
XML_DIR = "xml_downloads"
OUT_DIR = "output"
os.makedirs(XML_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

# Logo path (you said you can only have logo.png at repo root)
LOGO_PATH = "logo.png"

# Image styling
IMG_W, IMG_H = 1080, 1080
BACKGROUND_COLOR = (0x1F, 0x2A, 0x4D)   # #1F2A4D
GOLD = (0xFF, 0xBA, 0x00)               # #FFBA00 (headings)
WHITE = (0xFF, 0xFF, 0xFF)              # #FFFFFF (body text)

LEFT_MARGIN = 80
RIGHT_MARGIN = 80
TOP_MARGIN = 60
BOTTOM_MARGIN = 80

# Base font sizes (will be scaled down to fit)
BASE_TITLE_SIZE = 54
BASE_HEADING_SIZE = 40
BASE_BODY_SIZE = 30
MIN_SCALE = 0.6  # Don't shrink below 60% of base size

# --------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------

def ordinal(n: int) -> str:
    """Return ordinal string for an integer: 1 -> '1st', 2 -> '2nd', etc."""
    suffix = "th"
    if n % 10 == 1 and n % 100 != 11:
        suffix = "st"
    elif n % 10 == 2 and n % 100 != 12:
        suffix = "nd"
    elif n % 10 == 3 and n % 100 != 13:
        suffix = "rd"
    return f"{n}{suffix}"


def get_target_date_str() -> str:
    """
    Target = tomorrow's date (for tomorrow's stats).
    Format matches Meeting/@date like '29/11/2025'.
    """
    today = date.today()
    target = today + timedelta(days=1)
    s = target.strftime("%d/%m/%Y")
    print(f"Target meeting date: {s}")
    return s


def ftp_download_all_xml():
    """
    Download ALL .xml files from FTP into XML_DIR.
    Return list of local file paths.
    """
    print("Connecting to FTP...")
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    names = ftp.nlst()

    xml_files = [n for n in names if n.lower().endswith(".xml")]
    if not xml_files:
        print("No XML files found on FTP.")
        ftp.quit()
        return []

    local_paths = []
    for fname in xml_files:
        print(f"Downloading {fname} from FTP...")
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {fname}", bio.write)
        bio.seek(0)
        local_path = os.path.join(XML_DIR, fname)
        with open(local_path, "wb") as f:
            f.write(bio.read())
        local_paths.append(local_path)

    ftp.quit()
    print("Downloaded XML files:", local_paths)
    return local_paths


def parse_meeting_file(path, target_date_str):
    """
    Parse one XML file and return meeting data dict
    if the Meeting/@date matches target_date_str, else None.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    if meeting is None:
        return None

    m_date = meeting.attrib.get("date", "")
    if m_date != target_date_str:
        return None

    meeting_name = meeting.attrib.get("name", "").strip()
    course = meeting.find("Course")
    tla = course.attrib.get("tla", "").strip() if course is not None else ""

    stats = meeting.find("MiscStatistics")
    if stats is None:
        return None

    topx = stats.find("TopXStatistics")

    def get_topx_list(stat_type):
        if topx is None:
            return []
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                return s.findall("Statistic")
        return []

    top_track_trainers = get_topx_list("TopTrackTrainers")[:5]
    top_track_jockeys = get_topx_list("TopTrackJockeys")[:5]
    hot_trainers = get_topx_list("HotTrainers")[:5]
    hot_jockeys = get_topx_list("HotJockeys")[:5]

    # Dropping in class
    drop_section = stats.find("RunnerDropInClass")
    drop_runners = drop_section.findall("Runner") if drop_section is not None else []

    # Well handicapped
    won_section = stats.find("WonOffHigherHandicap")
    won_runners = won_section.findall("Runner") if won_section is not None else []
    won_runners = won_runners[:5]

    return {
        "meeting_name": meeting_name,
        "tla": tla,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }


# --------------------------------------------------------------------
# TEXT LAYOUT AND RENDERING
# --------------------------------------------------------------------

def load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Try a reasonably standard TTF on GitHub runners, fall back to default.
    """
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def build_lines_top_track(meeting_data):
    mname = meeting_data["meeting_name"]
    lines = []

    # Title
    lines.append({
        "text": f"{mname} — Top Track Trainers & Jockeys (Last 5 Years)",
        "style": "title"
    })

    # Trainers
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": f"Top Track Trainers at {mname} (Last 5 Years)", "style": "heading"})
    if meeting_data["top_track_trainers"]:
        for stat in meeting_data["top_track_trainers"]:
            rank = int(stat.attrib.get("rank", "0") or "0")
            name = stat.attrib.get("name", "")
            wins = stat.attrib.get("wins", "")
            runs = stat.attrib.get("runs", "")
            sr = stat.attrib.get("strikeRate", "")
            lines.append({
                "text": f"{ordinal(rank)} {name} – {sr}% strike rate ({wins} wins from {runs} runners)",
                "style": "body"
            })
    else:
        lines.append({"text": "No Top Track Trainer data available.", "style": "body"})

    # Jockeys
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": f"Top Track Jockeys at {mname} (Last 5 Years)", "style": "heading"})
    if meeting_data["top_track_jockeys"]:
        for stat in meeting_data["top_track_jockeys"]:
            rank = int(stat.attrib.get("rank", "0") or "0")
            name = stat.attrib.get("name", "")
            wins = stat.attrib.get("wins", "")
            runs = stat.attrib.get("runs", "")
            sr = stat.attrib.get("strikeRate", "")
            lines.append({
                "text": f"{ordinal(rank)} {name} – {sr}% strike rate ({wins} wins from {runs} rides)",
                "style": "body"
            })
    else:
        lines.append({"text": "No Top Track Jockey data available.", "style": "body"})

    return lines


def build_lines_hot(meeting_data):
    mname = meeting_data["meeting_name"]
    lines = []

    lines.append({
        "text": f"{mname} — Hot Trainers & Jockeys (Last Month)",
        "style": "title"
    })

    # Hot Trainers
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": "Hot Trainers (Last Month)", "style": "heading"})
    if meeting_data["hot_trainers"]:
        for stat in meeting_data["hot_trainers"]:
            rank = int(stat.attrib.get("rank", "0") or "0")
            name = stat.attrib.get("name", "")
            wins = stat.attrib.get("wins", "")
            runs = stat.attrib.get("runs", "")
            sr = stat.attrib.get("strikeRate", "")
            lines.append({
                "text": f"{ordinal(rank)} {name} – {sr}% strike rate ({wins} wins from {runs} runners)",
                "style": "body"
            })
    else:
        lines.append({"text": "No Hot Trainer data available.", "style": "body"})

    # Hot Jockeys
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": "Hot Jockeys (Last Month)", "style": "heading"})
    if meeting_data["hot_jockeys"]:
        for stat in meeting_data["hot_jockeys"]:
            rank = int(stat.attrib.get("rank", "0") or "0")
            name = stat.attrib.get("name", "")
            wins = stat.attrib.get("wins", "")
            runs = stat.attrib.get("runs", "")
            sr = stat.attrib.get("strikeRate", "")
            lines.append({
                "text": f"{ordinal(rank)} {name} – {sr}% strike rate ({wins} wins from {runs} rides)",
                "style": "body"
            })
    else:
        lines.append({"text": "No Hot Jockey data available.", "style": "body"})

    return lines


def build_lines_class_and_handicap(meeting_data):
    mname = meeting_data["meeting_name"]
    lines = []

    lines.append({
        "text": f"{mname} — Dropping in Class & Well Handicapped Today",
        "style": "title"
    })

    # Dropping in class
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": f"Runners at {mname} dropping in class:", "style": "heading"})
    drops = meeting_data["drop_runners"]
    if drops:
        for r in drops:
            name = r.attrib.get("name", "")
            rtime = r.attrib.get("raceTime", "")
            lines.append({
                "text": f"{name} runs in the {rtime}",
                "style": "body"
            })
    else:
        lines.append({"text": "No runners dropping in class today.", "style": "body"})

    # Well handicapped
    lines.append({"text": "", "style": "spacer"})
    lines.append({"text": f"Well handicapped horses running at {mname} today:", "style": "heading"})
    won = meeting_data["won_runners"]
    if won:
        for r in won:
            name = r.attrib.get("name", "")
            rtime = r.attrib.get("raceTime", "")
            weight_node = r.find("Weight")
            desc = ""
            if weight_node is not None:
                then_w = weight_node.attrib.get("weightThen", "")
                now_w = weight_node.attrib.get("weightNow", "")
                try:
                    diff = int(then_w) - int(now_w)
                    if diff > 0:
                        desc = f"won off a {diff} lb higher mark – runs in the {rtime} today"
                    else:
                        desc = f"runs in the {rtime} today"
                except Exception:
                    desc = f"runs in the {rtime} today"
            else:
                desc = f"runs in the {rtime} today"

            lines.append({
                "text": f"{name} {desc}",
                "style": "body"
            })
    else:
        lines.append({"text": "No well handicapped horses today.", "style": "body"})

    return lines


def measure_total_height(lines, content_height_available):
    """
    Find a scale factor so that all lines fit into the available content height.
    We use a dummy image and textbbox (not textsize) for measurement.
    """
    dummy = Image.new("RGB", (IMG_W, IMG_H))
    draw = ImageDraw.Draw(dummy)

    def font_for(style, scale):
        if style == "title":
            size = max(int(BASE_TITLE_SIZE * scale), 12)
        elif style == "heading":
            size = max(int(BASE_HEADING_SIZE * scale), 12)
        else:  # body or spacer
            size = max(int(BASE_BODY_SIZE * scale), 12)
        return load_font(size)

    def total_height(scale):
        y = 0
        for line in lines:
            if line["style"] == "spacer":
                # explicit spacer line
                y += int(18 * scale)
                continue
            text = line["text"]
            if not text:
                y += int(10 * scale)
                continue
            font = font_for(line["style"], scale)
            bbox = draw.textbbox((0, 0), text, font=font)
            h = bbox[3] - bbox[1]
            # line height + gap between lines
            y += h + int(10 * scale)
        return y

    scale = 1.0
    h = total_height(scale)
    while h > content_height_available and scale > MIN_SCALE:
        scale -= 0.05
        h = total_height(scale)

    return max(scale, MIN_SCALE)


def render_post_image(lines, out_path):
    """
    Render a single 1080x1080 image with dynamic scaling of fonts
    so that all lines fit inside the content area.
    """
    # Measure logo size (if present) first
    logo = None
    logo_height = 0
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            # Make logo nicely visible: taller than before
            max_logo_width = 260
            max_logo_height = 180
            logo.thumbnail((max_logo_width, max_logo_height))
            logo_height = logo.size[1]
        except Exception as e:
            print("Failed to load logo:", e)
            logo = None
            logo_height = 0

    # Compute content top based on logo
    if logo is not None:
        content_top_y = TOP_MARGIN + logo_height + 30
    else:
        content_top_y = TOP_MARGIN + 20

    content_bottom_y = IMG_H - BOTTOM_MARGIN
    content_height = content_bottom_y - content_top_y

    # Find scale factor
    scale = measure_total_height(lines, content_height)
    print(f"Using scale factor: {scale:.2f} for {out_path}")

    # Helper for fonts
    def font_for(style):
        if style == "title":
            size = max(int(BASE_TITLE_SIZE * scale), 12)
        elif style == "heading":
            size = max(int(BASE_HEADING_SIZE * scale), 12)
        else:
            size = max(int(BASE_BODY_SIZE * scale), 12)
        return load_font(size)

    # Draw final image
    im = Image.new("RGB", (IMG_W, IMG_H), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(im)

    # Paste logo
    if logo is not None:
        im.paste(logo, (LEFT_MARGIN, TOP_MARGIN), logo)

    y = content_top_y

    for line in lines:
        style = line["style"]
        if style == "spacer":
            y += int(18 * scale)
            continue

        text = line["text"]
        if not text:
            y += int(10 * scale)
            continue

        font = font_for(style)
        # Colours: headings/title gold, rest white
        if style in ("title", "heading"):
            color = GOLD
        else:
            color = WHITE

        # Left aligned text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = LEFT_MARGIN
        draw.text((x, y), text, font=font, fill=color)
        y += text_h + int(10 * scale)

    im.save(out_path)
    print("Saved image:", out_path)
    return out_path


# --------------------------------------------------------------------
# EMAIL
# --------------------------------------------------------------------

def send_email_with_images(image_paths):
    """
    Send one email with all generated images attached.
    """
    if not image_paths:
        print("No images to email – skipping email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached.\n\nEach meeting has 3 images:\n1) Top Track Trainers/Jockeys\n2) Hot Trainers/Jockeys\n3) Dropping in Class & Well Handicapped.")

    for path in image_paths:
        with open(path, "rb") as f:
            data = f.read()
        filename = os.path.basename(path)
        msg.add_attachment(data, maintype="image", subtype="png", filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print(f"Emailed {len(image_paths)} images to {EMAIL_ADDRESS}")


# --------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------

def main():
    target_date_str = get_target_date_str()

    xml_paths = ftp_download_all_xml()
    if not xml_paths:
        print("No XML paths downloaded, exiting.")
        return

    # Parse meetings for target date
    meetings = []
    for path in xml_paths:
        try:
            m = parse_meeting_file(path, target_date_str)
            if m is not None:
                meetings.append(m)
        except Exception as e:
            print(f"Error parsing {path}: {e}")

    if not meetings:
        print(f"No meetings found for {target_date_str}.")
        return

    print(f"Found {len(meetings)} meetings for target date.")

    all_images = []

    for m in meetings:
        tla = m["tla"] or "MEETING"
        tla_safe = tla.replace("/", "_")

        # Post 1: Top track trainers/jockeys
        lines1 = build_lines_top_track(m)
        out1 = os.path.join(OUT_DIR, f"{tla_safe}_1_top_track.png")
        render_post_image(lines1, out1)
        all_images.append(out1)

        # Post 2: Hot trainers/jockeys
        lines2 = build_lines_hot(m)
        out2 = os.path.join(OUT_DIR, f"{tla_safe}_2_hot.png")
        render_post_image(lines2, out2)
        all_images.append(out2)

        # Post 3: Dropping in class + well handicapped
        lines3 = build_lines_class_and_handicap(m)
        out3 = os.path.join(OUT_DIR, f"{tla_safe}_3_class_handicap.png")
        render_post_image(lines3, out3)
        all_images.append(out3)

    # Send one email with all images
    send_email_with_images(all_images)


if __name__ == "__main__":
    main()
