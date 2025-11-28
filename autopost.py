import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

# --- Configuration from environment (GitHub Secrets) ---
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

LOCAL_XML = "meeting.xml"  # temporary path if we ever need it
OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

# Colours
BG_COLOUR = (0x1F, 0x2A, 0x4D)      # deep navy
WHITE = (255, 255, 255)
GOLD = (0xFF, 0xBA, 0x00)

IMAGE_SIZE = (1080, 1080)


def load_font(size, bold=False):
    """Try to load a decent TTF font; fall back to default if not available."""
    try:
        # DejaVu is usually available on GitHub runners
        if bold:
            return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        else:
            return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


TITLE_FONT = load_font(60, bold=True)
SECTION_FONT = load_font(40, bold=True)
BODY_FONT = load_font(32, bold=False)


def rank_to_label(rank_str: str) -> str:
    try:
        n = int(rank_str)
    except (TypeError, ValueError):
        return rank_str or ""
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


def get_target_ddmm():
    """Return tomorrow's date in ddmm string, e.g. '2911'."""
    today = datetime.utcnow().date()
    target = today + timedelta(days=1)
    return f"{target.day:02d}{target.month:02d}"


def list_tomorrows_xml_files():
    """List XML filenames on the FTP whose ddmm part matches tomorrow."""
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()
    ftp.quit()

    target_ddmm = get_target_ddmm()
    xml_files = []
    for name in files:
        if not name.lower().endswith(".xml"):
            continue
        base = os.path.basename(name)
        parts = base.split("-")
        if len(parts) < 3:
            continue
        ddmm = parts[-1].split(".")[0]
        if ddmm == target_ddmm:
            xml_files.append(base)
    return xml_files


def download_xml_file(filename):
    """Download a single XML file from FTP and return its local path."""
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    bio = io.BytesIO()
    ftp.retrbinary(f"RETR {filename}", bio.write)
    ftp.quit()
    bio.seek(0)
    local_path = os.path.join(OUT_DIR, filename)
    with open(local_path, "wb") as f:
        f.write(bio.read())
    return local_path


def parse_meeting(path):
    """Parse one meeting XML and return meeting name, tla and relevant stats."""
    tree = ET.parse(path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    if meeting is None:
        raise ValueError("No <Meeting> node found")

    meeting_name = meeting.attrib.get("name", "").strip()
    course = meeting.find("Course")
    tla = course.attrib.get("tla", "").strip() if course is not None else ""

    stats = meeting.find("MiscStatistics")
    if stats is None:
        raise ValueError("No <MiscStatistics> found")
    topx = stats.find("TopXStatistics")
    if topx is None:
        raise ValueError("No <TopXStatistics> found")

    def get_top_list(stat_type, limit=5):
        node = None
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                node = s
                break
        out = []
        if node is not None:
            for st in node.findall("Statistic")[:limit]:
                out.append({
                    "rank": st.attrib.get("rank"),
                    "name": st.attrib.get("name"),
                    "wins": st.attrib.get("wins"),
                    "runs": st.attrib.get("runs"),
                    "strikeRate": st.attrib.get("strikeRate"),
                })
        return out

    top_track_trainers = get_top_list("TopTrackTrainers")
    top_track_jockeys = get_top_list("TopTrackJockeys")
    hot_trainers = get_top_list("HotTrainers")
    hot_jockeys = get_top_list("HotJockeys")

    # Dropping in class
    drop_list = []
    drop_node = stats.find("RunnerDropInClass")
    if drop_node is not None:
        for r in drop_node.findall("Runner"):
            drop_list.append({
                "name": r.attrib.get("name"),
                "raceTime": r.attrib.get("raceTime"),
            })

    # Well handicapped (WonOffHigherHandicap) - first 5 only
    well_list = []
    won_node = stats.find("WonOffHigherHandicap")
    if won_node is not None:
        for r in won_node.findall("Runner")[:5]:
            weight_node = r.find("Weight")
            weight_then = weight_node.attrib.get("weightThen") if weight_node is not None else ""
            weight_now = weight_node.attrib.get("weightNow") if weight_node is not None else ""
            diff = ""
            try:
                if weight_then and weight_now:
                    diff_val = int(weight_then) - int(weight_now)
                    if diff_val > 0:
                        diff = str(diff_val)
            except ValueError:
                diff = ""
            well_list.append({
                "name": r.attrib.get("name"),
                "raceTime": r.attrib.get("raceTime"),
                "weightThen": weight_then,
                "weightNow": weight_now,
                "diff": diff,
            })

    return {
        "meeting_name": meeting_name,
        "tla": tla,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "dropping": drop_list,
        "well": well_list,
    }


def paste_logo(im, max_width=220):
    """Paste logo.png in top-left (B2 style), scaled, and return the bottom y of logo area."""
    logo_path = "logo.png"  # placed in repo root
    y_bottom = 40
    if not os.path.exists(logo_path):
        return y_bottom
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return y_bottom
    # Scale
    w, h = logo.size
    if w > max_width:
        ratio = max_width / float(w)
        logo = logo.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        w, h = logo.size
    im.paste(logo, (40, 40), logo)
    return 40 + h + 30  # start text below logo


def render_post1(meeting_data, out_path):
    """Post 1: Top track trainers & jockeys (last 5 years)."""
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    y = paste_logo(im)

    title = f"{meeting_data['meeting_name']} — Track Stats"
    draw.text((40, y), title, font=TITLE_FONT, fill=WHITE)
    y += 70

    # Section: Top Track Trainers
    heading = f"Top Track Trainers at {meeting_data['meeting_name']} — Last 5 Years"
    draw.text((40, y), heading, font=SECTION_FONT, fill=WHITE)
    y += 50
    for row in meeting_data["top_track_trainers"]:
        rank_label = rank_to_label(row["rank"])
        line = (
            f"{rank_label} {row['name']} {row['strikeRate']}% strike rate "
            f"({row['wins']} wins from {row['runs']} runners)"
        )
        draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
        y += 38

    y += 30
    # Section: Top Track Jockeys
    heading2 = f"Top Track Jockeys at {meeting_data['meeting_name']} — Last 5 Years"
    draw.text((40, y), heading2, font=SECTION_FONT, fill=WHITE)
    y += 50
    for row in meeting_data["top_track_jockeys"]:
        rank_label = rank_to_label(row["rank"])
        line = (
            f"{rank_label} {row['name']} {row['strikeRate']}% strike rate "
            f"({row['wins']} wins from {row['runs']} rides)"
        )
        draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
        y += 38

    im.save(out_path)
    return out_path


def render_post2(meeting_data, out_path):
    """Post 2: Hot trainers/jockeys (last month)."""
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    y = paste_logo(im)

    title = f"{meeting_data['meeting_name']} — Hot Form"
    draw.text((40, y), title, font=TITLE_FONT, fill=WHITE)
    y += 70

    # Hot Trainers
    heading = "Hot Trainers (Last Month)"
    draw.text((40, y), heading, font=SECTION_FONT, fill=WHITE)
    y += 50
    for row in meeting_data["hot_trainers"]:
        rank_label = rank_to_label(row["rank"])
        line = (
            f"{rank_label} {row['name']} {row['strikeRate']}% strike rate "
            f"({row['wins']} wins from {row['runs']} runners)"
        )
        draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
        y += 38

    y += 30
    # Hot Jockeys
    heading2 = "Hot Jockeys (Last Month)"
    draw.text((40, y), heading2, font=SECTION_FONT, fill=WHITE)
    y += 50
    for row in meeting_data["hot_jockeys"]:
        rank_label = rank_to_label(row["rank"])
        line = (
            f"{rank_label} {row['name']} {row['strikeRate']}% strike rate "
            f"({row['wins']} wins from {row['runs']} rides)"
        )
        draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
        y += 38

    im.save(out_path)
    return out_path


def render_post3(meeting_data, out_path):
    """Post 3: Dropping in class & well handicapped."""
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    y = paste_logo(im)

    title = f"{meeting_data['meeting_name']} — Handicapping Angles"
    draw.text((40, y), title, font=TITLE_FONT, fill=WHITE)
    y += 70

    # Dropping in class
    heading = f"Today's runners at {meeting_data['meeting_name']} dropping in class:"
    draw.text((40, y), heading, font=SECTION_FONT, fill=WHITE)
    y += 50

    if meeting_data["dropping"]:
        for r in meeting_data["dropping"]:
            rt = r.get("raceTime") or ""
            line = f"• {r['name']} running in the {rt}"
            draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
            y += 38
    else:
        draw.text((60, y), "• None today", font=BODY_FONT, fill=GOLD)
        y += 38

    y += 30
    # Well handicapped
    heading2 = f"Well handicapped horses running at {meeting_data['meeting_name']} today:"
    draw.text((40, y), heading2, font=SECTION_FONT, fill=WHITE)
    y += 50

    if meeting_data["well"]:
        for r in meeting_data["well"]:
            rt = r.get("raceTime") or ""
            if r["diff"]:
                line = (
                    f"• {r['name']} won off a {r['diff']}lb higher mark – "
                    f"runs in the {rt} today"
                )
            else:
                line = f"• {r['name']} – runs in the {rt} today"
            draw.text((60, y), line, font=BODY_FONT, fill=GOLD)
            y += 38
    else:
        draw.text((60, y), "• None highlighted today", font=BODY_FONT, fill=GOLD)
        y += 38

    im.save(out_path)
    return out_path


def send_email_with_images(image_paths):
    """Send a single email with all generated images attached."""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise RuntimeError("EMAIL_ADDRESS or EMAIL_APP_PASSWORD not set")

    target_ddmm = get_target_ddmm()
    subject = f"Racing graphics for {target_ddmm}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content(
        "Your daily racing graphics are attached.\n\nOne set per meeting (3 images each)."
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


def main():
    # 1) Find tomorrow's XML files
    xml_files = list_tomorrows_xml_files()
    if not xml_files:
        print("No XML files found for tomorrow's date. Nothing to do.")
        return

    all_image_paths = []

    for filename in xml_files:
        local_xml = download_xml_file(filename)
        meeting_data = parse_meeting(local_xml)

        base_tag = meeting_data["tla"] or meeting_data["meeting_name"].replace(" ", "")
        base_tag = base_tag.replace("/", "").replace("\\", "")

        p1 = os.path.join(OUT_DIR, f"{base_tag}_post1.png")
        p2 = os.path.join(OUT_DIR, f"{base_tag}_post2.png")
        p3 = os.path.join(OUT_DIR, f"{base_tag}_post3.png")

        render_post1(meeting_data, p1)
        render_post2(meeting_data, p2)
        render_post3(meeting_data, p3)

        all_image_paths.extend([p1, p2, p3])

    send_email_with_images(all_image_paths)
    print(f"Email sent with {len(all_image_paths)} images attached.")


if __name__ == "__main__":
    main()
