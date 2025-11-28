import os
import ftplib
import io
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

# --------- ENV / CONFIG ---------
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

BG_COLOR = (0x1F, 0x2A, 0x4D)      # deep navy #1F2A4D
WHITE = (255, 255, 255)
GOLD = (0xFF, 0xBA, 0x00)          # #FFBA00

LOGO_PATH = "assets/logo.png"

# --------- SMALL HELPERS ---------
def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def rank_emoji(rank: int) -> str:
    return {1: "🏆", 2: "🥈", 3: "🥉"}.get(rank, "•")

def load_fonts():
    # try a nice sans font available on GitHub runners
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        section_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        body_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        title_font = section_font = body_font = ImageFont.load_default()
    return title_font, section_font, body_font

def draw_multiline(draw, text, xy, font, fill, max_width):
    """
    Simple word wrapping so long lines don’t run off the edge.
    """
    x, y = xy
    words = text.split()
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        w, _ = draw.textsize(test, font=font)
        if w <= max_width:
            line = test
        else:
            draw.text((x, y), line, font=font, fill=fill)
            y += font.size + 4
            line = word
    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + 6
    return y

# --------- FTP + XML ---------
def list_tomorrows_xml_files():
    """
    List all XML files on the FTP where the filename ends with -DDMM.xml for TOMORROW (UTC),
    e.g. 5-NBU-2911.xml for 29/11.
    """
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()

    tomorrow_ddmm = (datetime.utcnow() + timedelta(days=1)).strftime("%d%m")
    matches = []
    for name in files:
        if not name.lower().endswith(".xml"):
            continue
        core = os.path.splitext(os.path.basename(name))[0]
        parts = core.split("-")
        if len(parts) >= 3 and parts[-1] == tomorrow_ddmm:
            matches.append(name)

    return ftp, matches  # caller is responsible for ftp.quit()

def parse_meeting_xml(xml_bytes):
    root = ET.fromstring(xml_bytes)
    meeting = root.find("Meeting")
    course = meeting.find("Course")
    meeting_name = meeting.attrib.get("name", "").strip()
    course_name = course.attrib.get("name", "").strip()

    stats = meeting.find("MiscStatistics")
    topx = stats.find("TopXStatistics")

    def get_top_list(stat_type):
        node = None
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                node = s
                break
        if node is None:
            return []
        items = []
        for stat in node.findall("Statistic")[:5]:
            items.append({
                "rank": int(stat.attrib.get("rank", "0")),
                "name": stat.attrib.get("name", ""),
                "wins": stat.attrib.get("wins", ""),
                "runs": stat.attrib.get("runs", ""),
                "strikeRate": stat.attrib.get("strikeRate", "")
            })
        return items

    top_track_trainers = get_top_list("TopTrackTrainers")
    top_track_jockeys = get_top_list("TopTrackJockeys")
    hot_trainers = get_top_list("HotTrainers")
    hot_jockeys = get_top_list("HotJockeys")

    # Dropping in class
    drop_runners = []
    drop_node = stats.find("RunnerDropInClass")
    if drop_node is not None:
        for r in drop_node.findall("Runner"):
            drop_runners.append({
                "name": r.attrib.get("name", ""),
                "raceTime": r.attrib.get("raceTime", "")
            })

    # Well handicapped
    won_runners = []
    won_node = stats.find("WonOffHigherHandicap")
    if won_node is not None:
        for r in won_node.findall("Runner")[:5]:
            wt = r.find("Weight")
            try:
                then_w = int(wt.attrib.get("weightThen", "0")) if wt is not None else 0
                now_w = int(wt.attrib.get("weightNow", "0")) if wt is not None else 0
            except ValueError:
                then_w = now_w = 0
            diff = then_w - now_w
            won_runners.append({
                "name": r.attrib.get("name", ""),
                "raceTime": r.attrib.get("raceTime", ""),
                "lb_diff": diff
            })

    return {
        "meeting_name": meeting_name,
        "course_name": course_name,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }

# --------- RENDERING ---------
def render_post1(meeting_data):
    course = meeting_data["course_name"]
    title_font, section_font, body_font = load_fonts()

    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Logo top-left
    top_y = 40
    left_x = 40
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        target_height = 120
        ratio = target_height / logo.height
        logo = logo.resize((int(logo.width * ratio), target_height), Image.LANCZOS)
        img.paste(logo, (left_x, top_y), logo)
        content_top = top_y + target_height + 20
    else:
        content_top = top_y + 20

    # Main title
    title_text = f"{course} – Key Stats"
    tw, th = draw.textsize(title_text, font=title_font)
    draw.text(((W - tw) // 2, top_y), title_text, font=title_font, fill=WHITE)

    y = content_top

    col_gap = 40
    col_width = (W - 2 * left_x - col_gap) // 2
    col1_x = left_x
    col2_x = left_x + col_width + col_gap

    # LEFT COLUMN: Top Track Trainers, Hot Trainers
    y1 = y
    y1 = draw_section_list(
        draw,
        x=col1_x,
        y=y1,
        heading=f"Top Track Trainers at {course}\nLast 5 Years",
        items=meeting_data["top_track_trainers"],
        section_font=section_font,
        body_font=body_font,
        max_width=col_width,
        runner_word="runners"
    )
    y1 += 20
    y1 = draw_section_list(
        draw,
        x=col1_x,
        y=y1,
        heading="Hot Trainers (Last Month)",
        items=meeting_data["hot_trainers"],
        section_font=section_font,
        body_font=body_font,
        max_width=col_width,
        runner_word="runners"
    )

    # RIGHT COLUMN: Top Track Jockeys, Hot Jockeys
    y2 = y
    y2 = draw_section_list(
        draw,
        x=col2_x,
        y=y2,
        heading=f"Top Track Jockeys at {course}\nLast 5 Years",
        items=meeting_data["top_track_jockeys"],
        section_font=section_font,
        body_font=body_font,
        max_width=col_width,
        runner_word="rides"
    )
    y2 += 20
    y2 = draw_section_list(
        draw,
        x=col2_x,
        y=y2,
        heading="Hot Jockeys (Last Month)",
        items=meeting_data["hot_jockeys"],
        section_font=section_font,
        body_font=body_font,
        max_width=col_width,
        runner_word="rides"
    )

    filename = os.path.join(OUT_DIR, f"{course.replace(' ', '_')}_post1.png")
    img.save(filename, format="PNG")
    return filename

def draw_section_list(draw, x, y, heading, items, section_font, body_font, max_width, runner_word):
    # heading in gold
    y = draw_multiline(draw, heading, (x, y), section_font, GOLD, max_width)
    for it in items:
        rank = it["rank"]
        name = it["name"]
        wins = it["wins"]
        runs = it["runs"]
        sr = it["strikeRate"]
        line = (
            f"{ordinal(rank)} {rank_emoji(rank)} {name} "
            f"{sr}% strike rate ({wins} wins from {runs} {runner_word})"
        )
        y = draw_multiline(draw, line, (x, y), body_font, WHITE, max_width)
    return y

def render_post2(meeting_data):
    course = meeting_data["course_name"]
    title_font, section_font, body_font = load_fonts()

    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Logo top-left
    top_y = 40
    left_x = 40
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        target_height = 120
        ratio = target_height / logo.height
        logo = logo.resize((int(logo.width * ratio), target_height), Image.LANCZOS)
        img.paste(logo, (left_x, top_y), logo)
        content_top = top_y + target_height + 20
    else:
        content_top = top_y + 20

    # Title
    title_text = f"{course} – Class & Handicap Angles"
    tw, th = draw.textsize(title_text, font=title_font)
    draw.text(((W - tw) // 2, top_y), title_text, font=title_font, fill=WHITE)

    x = left_x
    y = content_top

    max_width = W - 2 * left_x

    # Dropping in class
    y = draw_multiline(
        draw,
        f"Today's runners at {course} dropping in class:",
        (x, y),
        section_font,
        GOLD,
        max_width,
    )
    if meeting_data["drop_runners"]:
        for r in meeting_data["drop_runners"]:
            line = f"• {r['name']} running in the {r['raceTime']}"
            y = draw_multiline(draw, line, (x, y), body_font, WHITE, max_width)
    else:
        y = draw_multiline(draw, "• None today", (x, y), body_font, WHITE, max_width)

    y += 30

    # Well handicapped
    y = draw_multiline(
        draw,
        f"Well handicapped horses running at {course} today:",
        (x, y),
        section_font,
        GOLD,
        max_width,
    )
    if meeting_data["won_runners"]:
        for r in meeting_data["won_runners"]:
            diff = r["lb_diff"]
            if diff > 0:
                diff_text = f"{diff}lb higher mark"
            elif diff < 0:
                diff_text = f"{abs(diff)}lb lower mark"
            else:
                diff_text = "the same mark"
            line = (
                f"• {r['name']} won off a {diff_text} – runs in the {r['raceTime']} today"
            )
            y = draw_multiline(draw, line, (x, y), body_font, WHITE, max_width)
    else:
        y = draw_multiline(draw, "• None flagged today", (x, y), body_font, WHITE, max_width)

    filename = os.path.join(OUT_DIR, f"{course.replace(' ', '_')}_post2.png")
    img.save(filename, format="PNG")
    return filename

# --------- EMAIL ---------
def send_email_with_images(image_paths):
    if not image_paths:
        print("No images to send.")
        return

    msg = EmailMessage()
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%d/%m/%Y")
    msg["Subject"] = f"HorseRacingHack – graphics for {tomorrow}'s meetings"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content(
        "Hi,\n\nAttached are today's ready-to-post graphics for tomorrow's meetings.\n\n"
        "Post 1 = trainers & jockeys stats\n"
        "Post 2 = dropping in class & well handicapped.\n\n"
        "– HorseRacingHack auto system"
    )

    for path in image_paths:
        with open(path, "rb") as f:
            data = f.read()
        filename = os.path.basename(path)
        msg.add_attachment(data, maintype="image", subtype="png", filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    print(f"Sent email with {len(image_paths)} attachments.")

# --------- MAIN ---------
def main():
    ftp, files = list_tomorrows_xml_files()
    print("Tomorrow's XML files:", files)

    all_images = []

    for fname in files:
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {fname}", bio.write)
        xml_bytes = bio.getvalue()
        meeting_data = parse_meeting_xml(xml_bytes)

        p1 = render_post1(meeting_data)
        p2 = render_post2(meeting_data)
        all_images.extend([p1, p2])

    ftp.quit()

    send_email_with_images(all_images)

if __name__ == "__main__":
    main()
