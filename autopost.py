import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

# -------- Environment variables (from GitHub Secrets) --------
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

# -------- Paths --------
OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

# Colours
BG_COLOUR = (0x1F, 0x2A, 0x4D)      # deep navy #1F2A4D
WHITE = (255, 255, 255)
GOLD = (0xFF, 0xBA, 0x00)           # #FFBA00
LIGHT_GOLD = (255, 210, 100)
GREY = (200, 200, 200)

IMAGE_SIZE = (1080, 1080)


# ---------------- Font helper (avoid "cannot open resource") ----------------
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    Try a couple of common fonts; if none available, fall back to default.
    This prevents the OSError 'cannot open resource' on GitHub runners.
    """
    candidates = []
    if bold:
        candidates = [
            "arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    # Fallback
    return ImageFont.load_default()


# ---------------- Emoji / rank helper ----------------
def rank_to_emoji(rank_str: str) -> str:
    try:
        r = int(rank_str)
    except (TypeError, ValueError):
        return ""
    mapping = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
        4: "4️⃣",
        5: "5️⃣",
    }
    return mapping.get(r, f"{r}.")


# ---------------- FTP helpers ----------------
def today_suffix_ddmm() -> str:
    # GH Actions runs at 10:00 UTC which is fine for UK/IRE meetings
    today = datetime.utcnow()
    return f"{today.day:02d}{today.month:02d}"


def download_todays_meeting_files() -> list:
    """
    Connect to FTP, find all XML files whose name pattern ends with DDMM (today),
    e.g. 5-NBU-2911.xml for 29/11.
    Returns list of local file paths.
    """
    suffix = today_suffix_ddmm()
    print("Looking for XML files with date suffix:", suffix)

    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()
    xml_files = [
        f for f in files
        if f.lower().endswith(".xml")
        and len(f) >= 9
        and f[-8:-4].isdigit()
        and f[-8:-4] == suffix
    ]

    if not xml_files:
        print("No date-matched XML files found; falling back to all XML files on FTP.")
        xml_files = [f for f in files if f.lower().endswith(".xml")]

    local_paths = []
    for filename in xml_files:
        print("Downloading", filename)
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {filename}", bio.write)
        bio.seek(0)
        local_path = os.path.join(OUT_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(bio.read())
        local_paths.append(local_path)

    ftp.quit()
    print("Downloaded", len(local_paths), "files.")
    return local_paths


# ---------------- XML parsing ----------------
def parse_meeting_xml(path: str) -> dict:
    """
    Parse one meeting XML file and extract:
    - course name / tla
    - TopTrackTrainers / TopTrackJockeys
    - HotTrainers / HotJockeys
    - RunnerDropInClass
    - WonOffHigherHandicap
    """
    tree = ET.parse(path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    if meeting is None:
        raise ValueError("No <Meeting> node in XML")

    course = meeting.find("Course")
    course_name = course.attrib.get("name") if course is not None else meeting.attrib.get("name", "Unknown")
    course_tla = course.attrib.get("tla") if course is not None else ""

    stats = meeting.find("MiscStatistics")
    if stats is None:
        raise ValueError("No <MiscStatistics> in XML")

    topx = stats.find("TopXStatistics")

    def get_top_list(stat_type: str, limit: int = 5):
        if topx is None:
            return []
        node = None
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                node = s
                break
        if node is None:
            return []
        out = []
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
    drop_runners = []
    drop_node = stats.find("RunnerDropInClass")
    if drop_node is not None:
        for r in drop_node.findall("Runner"):
            drop_runners.append({
                "name": r.attrib.get("name"),
                "raceTime": r.attrib.get("raceTime"),
            })

    # Well handicapped
    won_runners = []
    won_node = stats.find("WonOffHigherHandicap")
    if won_node is not None:
        for r in won_node.findall("Runner")[:5]:
            wt = ""
            wn = ""
            w_node = r.find("Weight")
            if w_node is not None:
                wt = w_node.attrib.get("weightThen", "")
                wn = w_node.attrib.get("weightNow", "")
            won_runners.append({
                "name": r.attrib.get("name"),
                "raceTime": r.attrib.get("raceTime"),
                "weightThen": wt,
                "weightNow": wn,
            })

    return {
        "course_name": course_name,
        "course_tla": course_tla,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }


# ---------------- Logo helper ----------------
def paste_logo(im: Image.Image) -> int:
    """
    Paste logo.png in top-left (B2 style), return x-offset for title text.
    If logo not found, returns a default left margin.
    """
    draw = ImageDraw.Draw(im)
    margin_left = 40
    logo_path = "logo.png"
    if not os.path.exists(logo_path):
        return margin_left

    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return margin_left

    # Make it nice and visible (height ~ 180px on 1080x1080)
    target_h = 180
    w, h = logo.size
    scale = target_h / float(h)
    new_w = int(w * scale)
    logo = logo.resize((new_w, target_h), Image.LANCZOS)

    im.paste(logo, (margin_left, 40), logo)

    # Title text starts to the right of logo
    title_x = margin_left + new_w + 30
    return title_x


# ---------------- Rendering posts ----------------
def render_post_toptrack(data: dict, out_path: str) -> str:
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    title_font = get_font(58, bold=True)
    section_font = get_font(42, bold=True)
    body_font = get_font(34, bold=False)

    # Logo + title
    title_x = paste_logo(im)
    y = 50

    course_name = data["course_name"]
    title = f"{course_name} — Top Trainers & Jockeys"
    draw.text((title_x, y), title, font=title_font, fill=WHITE)
    y += 90

    # Sections
    x_left = 80
    x_right = 560
    y_top = y

    # Top Track Trainers
    draw.text(
        (x_left, y_top),
        f"Top Track Trainers at {course_name} – Last 5 Years",
        font=section_font,
        fill=GOLD,
    )
    y_curr = y_top + 50
    for st in data["top_track_trainers"]:
        emoji = rank_to_emoji(st["rank"])
        line = f"{emoji} {st['name']} {st['strikeRate']}% strike rate ({st['wins']} wins from {st['runs']} runners)"
        draw.text((x_left, y_curr), line, font=body_font, fill=WHITE)
        y_curr += 38

    # Top Track Jockeys
    draw.text(
        (x_right, y_top),
        f"Top Track Jockeys at {course_name} – Last 5 Years",
        font=section_font,
        fill=GOLD,
    )
    y_curr2 = y_top + 50
    for st in data["top_track_jockeys"]:
        emoji = rank_to_emoji(st["rank"])
        line = f"{emoji} {st['name']} {st['strikeRate']}% strike rate ({st['wins']} wins from {st['runs']} rides)"
        draw.text((x_right, y_curr2), line, font=body_font, fill=WHITE)
        y_curr2 += 38

    im.save(out_path)
    print("Saved:", out_path)
    return out_path


def render_post_hot(data: dict, out_path: str) -> str:
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    title_font = get_font(58, bold=True)
    section_font = get_font(42, bold=True)
    body_font = get_font(34, bold=False)

    title_x = paste_logo(im)
    y = 50

    course_name = data["course_name"]
    title = f"{course_name} — Hot Trainers & Jockeys"
    draw.text((title_x, y), title, font=title_font, fill=WHITE)
    y += 90

    x_left = 80
    x_right = 560
    y_top = y

    # Hot Trainers
    draw.text(
        (x_left, y_top),
        "Hot Trainers (Last Month)",
        font=section_font,
        fill=GOLD,
    )
    y_curr = y_top + 50
    if data["hot_trainers"]:
        for st in data["hot_trainers"]:
            emoji = rank_to_emoji(st["rank"])
            line = f"{emoji} {st['name']} {st['strikeRate']}% strike rate ({st['wins']} wins from {st['runs']} runners)"
            draw.text((x_left, y_curr), line, font=body_font, fill=WHITE)
            y_curr += 38
    else:
        draw.text((x_left, y_curr), "No hot trainer data.", font=body_font, fill=GREY)

    # Hot Jockeys
    draw.text(
        (x_right, y_top),
        "Hot Jockeys (Last Month)",
        font=section_font,
        fill=GOLD,
    )
    y_curr2 = y_top + 50
    if data["hot_jockeys"]:
        for st in data["hot_jockeys"]:
            emoji = rank_to_emoji(st["rank"])
            line = f"{emoji} {st['name']} {st['strikeRate']}% strike rate ({st['wins']} wins from {st['runs']} rides)"
            draw.text((x_right, y_curr2), line, font=body_font, fill=WHITE)
            y_curr2 += 38
    else:
        draw.text((x_right, y_curr2), "No hot jockey data.", font=body_font, fill=GREY)

    im.save(out_path)
    print("Saved:", out_path)
    return out_path


def render_post_drops(data: dict, out_path: str) -> str:
    im = Image.new("RGB", IMAGE_SIZE, BG_COLOUR)
    draw = ImageDraw.Draw(im)

    title_font = get_font(58, bold=True)
    section_font = get_font(42, bold=True)
    body_font = get_font(34, bold=False)

    title_x = paste_logo(im)
    y = 50

    course_name = data["course_name"]
    title = f"{course_name} — Dropping in Class & Well Handicapped"
    draw.text((title_x, y), title, font=title_font, fill=WHITE)
    y += 80

    x_left = 80

    # Dropping in class
    draw.text(
        (x_left, y),
        f"Today's runners at {course_name} dropping in class:",
        font=section_font,
        fill=GOLD,
    )
    y += 50
    if data["drop_runners"]:
        for r in data["drop_runners"]:
            line = f"• {r['name']} — runs in the {r['raceTime']}"
            draw.text((x_left, y), line, font=body_font, fill=WHITE)
            y += 34
            if y > IMAGE_SIZE[1] - 260:
                break
    else:
        draw.text((x_left, y), "None today.", font=body_font, fill=GREY)
        y += 34

    # Well handicapped
    y += 40
    draw.text(
        (x_left, y),
        f"Well handicapped horses running at {course_name} today:",
        font=section_font,
        fill=GOLD,
    )
    y += 50

    if data["won_runners"]:
        for r in data["won_runners"]:
            wt = r["weightThen"]
            wn = r["weightNow"]
            diff_txt = ""
            try:
                if wt and wn:
                    diff = int(wt) - int(wn)
                    if diff > 0:
                        diff_txt = f"{diff}lb higher mark"
            except ValueError:
                pass

            if diff_txt:
                line = f"• {r['name']} — won off a {diff_txt}, runs in the {r['raceTime']} today"
            else:
                line = f"• {r['name']} — runs in the {r['raceTime']} today"

            draw.text((x_left, y), line, font=body_font, fill=WHITE)
            y += 34
            if y > IMAGE_SIZE[1] - 80:
                break
    else:
        draw.text((x_left, y), "None today.", font=body_font, fill=GREY)

    im.save(out_path)
    print("Saved:", out_path)
    return out_path


# ---------------- Email sending ----------------
def send_email_with_images(image_paths: list):
    today = datetime.utcnow().strftime("%d/%m/%Y")
    msg = EmailMessage()
    msg["Subject"] = f"Daily Racing Graphics – {today}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached (all meetings).")

    for path in image_paths:
        with open(path, "rb") as f:
            img_data = f.read()
        filename = os.path.basename(path)
        msg.add_attachment(
            img_data,
            maintype="image",
            subtype="png",
            filename=filename,
        )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    print("Email sent with", len(image_paths), "images.")


# ---------------- Main ----------------
def main():
    # 1) Download all today's meeting XML files
    local_xml_files = download_todays_meeting_files()
    if not local_xml_files:
        print("No XML files downloaded; aborting.")
        return

    all_images = []

    # 2) For each meeting, parse & render 3 posts
    for xml_path in local_xml_files:
        print("Processing XML:", xml_path)
        try:
            data = parse_meeting_xml(xml_path)
        except Exception as e:
            print("Failed to parse", xml_path, ":", e)
            continue

        course_tla = data["course_tla"] or "MEETING"
        base_name = os.path.splitext(os.path.basename(xml_path))[0]

        # Post 1: Top Track trainers/jockeys
        img1_path = os.path.join(OUT_DIR, f"{base_name}_toptrack.png")
        render_post_toptrack(data, img1_path)
        all_images.append(img1_path)

        # Post 2: Hot trainers/jockeys
        img2_path = os.path.join(OUT_DIR, f"{base_name}_hot.png")
        render_post_hot(data, img2_path)
        all_images.append(img2_path)

        # Post 3: Dropping & well handicapped
        img3_path = os.path.join(OUT_DIR, f"{base_name}_drops.png")
        render_post_drops(data, img3_path)
        all_images.append(img3_path)

    if all_images:
        send_email_with_images(all_images)
    else:
        print("No images generated; nothing to email.")


if __name__ == "__main__":
    main()
