import os
import ftplib
import io
import smtplib
import ssl
import datetime
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from typing import List, Dict, Any

from PIL import Image, ImageDraw, ImageFont

# ----------------- Config from environment -----------------
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

# Image constants
IMG_W = 1080
IMG_H = 1080
BG_COLOR = (31, 42, 77)          # deep navy #1F2A4D
HEADING_COLOR = (255, 186, 0)    # gold #FFBA00
BODY_COLOR = (255, 255, 255)     # white
MARGIN_X = 80
MARGIN_TOP = 80
MARGIN_BOTTOM = 80

# Your logo file – saved in repo root as logo.png
LOGO_PATH = "logo.png"


# ----------------- Font helpers -----------------
def load_font(candidates: List[str], size: int) -> ImageFont.ImageFont:
    """
    Try a few font names, fall back to default.
    """
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ----------------- FTP helpers -----------------
def ftp_connect() -> ftplib.FTP:
    if not FTP_SERVER or not FTP_USER or not FTP_PASS:
        raise RuntimeError("FTP credentials not set in environment")
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    return ftp


def list_xml_files_for_date(ftp: ftplib.FTP, target_date: datetime.date) -> List[str]:
    """
    Filter XML files on FTP by filename day+month (DDMM) and prefer 5- prefix.
    Example: 5-NBU-2911.xml -> 2911 for 29/11.
    """
    names = ftp.nlst()
    xml_names = [n for n in names if n.lower().endswith(".xml")]
    if not xml_names:
        return []

    ddmm = target_date.strftime("%d%m")
    # last 8..4 chars are DDMM
    filtered = [n for n in xml_names if len(n) >= 8 and n[-8:-4] == ddmm]

    if not filtered:
        # safety fallback (shouldn't normally happen)
        filtered = xml_names

    def prefix_rank(name: str) -> int:
        if name.startswith("5-"):
            return 0
        if name.startswith("10-"):
            return 1
        if name.startswith("20-"):
            return 2
        return 3

    filtered.sort(key=prefix_rank)
    return filtered


def download_xml_files(target_date: datetime.date) -> List[str]:
    ftp = ftp_connect()
    try:
        xml_names = list_xml_files_for_date(ftp, target_date)
        downloaded_paths: List[str] = []
        print(f"Target meeting date: {target_date.isoformat()}")
        for name in xml_names:
            print(f"Downloading {name} from FTP...")
            bio = io.BytesIO()
            try:
                ftp.retrbinary(f"RETR {name}", bio.write)
            except Exception as e:
                print(f"  -> failed: {e}")
                continue
            bio.seek(0)
            local_path = os.path.join(XML_DIR, name)
            with open(local_path, "wb") as f:
                f.write(bio.read())
            downloaded_paths.append(local_path)
        print("Downloaded XML files:", downloaded_paths)
        return downloaded_paths
    finally:
        ftp.quit()


# ----------------- XML parsing -----------------
def parse_meeting_file(path: str, target_date: datetime.date) -> Dict[str, Any] | None:
    tree = ET.parse(path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    if meeting is None:
        return None

    date_str = meeting.attrib.get("date")
    if not date_str:
        return None

    try:
        day, month, year = map(int, date_str.split("/"))
        meet_date = datetime.date(year, month, day)
    except Exception:
        return None

    # Only keep meetings for the requested date
    if meet_date != target_date:
        return None

    meeting_name = meeting.attrib.get("name", "").strip()
    course = meeting.find("Course")
    tla = course.attrib.get("tla") if course is not None else ""

    stats = meeting.find("MiscStatistics")
    if stats is None:
        return None

    topx = stats.find("TopXStatistics")
    if topx is None:
        return None

    def get_top_list(stat_type: str) -> List[Dict[str, str]]:
        node = None
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                node = s
                break
        items: List[Dict[str, str]] = []
        if node is not None:
            for st in node.findall("Statistic")[:5]:
                items.append({
                    "rank": st.attrib.get("rank", ""),
                    "name": st.attrib.get("name", ""),
                    "wins": st.attrib.get("wins", ""),
                    "runs": st.attrib.get("runs", ""),
                    "strikeRate": st.attrib.get("strikeRate", ""),
                })
        return items

    top_track_trainers = get_top_list("TopTrackTrainers")
    top_track_jockeys = get_top_list("TopTrackJockeys")
    hot_trainers = get_top_list("HotTrainers")
    hot_jockeys = get_top_list("HotJockeys")

    drop_runners: List[Dict[str, str]] = []
    drop_node = stats.find("RunnerDropInClass")
    if drop_node is not None:
        for r in drop_node.findall("Runner"):
            drop_runners.append({
                "name": r.attrib.get("name", ""),
                "raceTime": r.attrib.get("raceTime", ""),
            })

    won_runners: List[Dict[str, str]] = []
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
            except Exception:
                diff = ""
            won_runners.append({
                "name": r.attrib.get("name", ""),
                "raceTime": r.attrib.get("raceTime", ""),
                "diff": diff,
            })

    if not (top_track_trainers or top_track_jockeys or hot_trainers or hot_jockeys or drop_runners or won_runners):
        return None

    return {
        "meeting_name": meeting_name,
        "tla": tla,
        "date": meet_date,
        "top_track_trainers": top_track_trainers,
        "top_track_jockeys": top_track_jockeys,
        "hot_trainers": hot_trainers,
        "hot_jockeys": hot_jockeys,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }


def ordinal(rank_str: str) -> str:
    try:
        n = int(rank_str)
    except Exception:
        return rank_str
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ----------------- Text layout helpers -----------------
def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    """
    Simple word-wrap so lines don't go off the edge.
    """
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for w in words[1:]:
        test = current + " " + w
        if text_width(draw, test, font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def load_logo() -> Image.Image | None:
    if not os.path.exists(LOGO_PATH):
        print("Logo file not found at", LOGO_PATH)
        return None
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
    except Exception as e:
        print("Could not open logo:", e)
        return None
    
    # Scale logo proportionally - max 25% of image width, target height ~15% of image
    target_h = int(IMG_H * 0.15)  # 162px for 1080x1080
    max_w = int(IMG_W * 0.25)      # 270px max width
    
    w, h = logo.size
    if h == 0 or w == 0:
        return logo
    
    # Scale by height first
    scale = target_h / float(h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    # If width exceeds max, scale down by width instead
    if new_w > max_w:
        scale = max_w / float(w)
        new_w = int(w * scale)
        new_h = int(h * scale)
    
    return logo.resize((new_w, new_h), Image.LANCZOS)


def calculate_content_height(draw: ImageDraw.ImageDraw, title: str, sections: List[Dict[str, Any]], 
                            title_font: ImageFont.ImageFont, section_font: ImageFont.ImageFont, 
                            body_font: ImageFont.ImageFont, max_text_width: int, logo_height: int) -> int:
    """Calculate total height needed for all content"""
    height = MARGIN_TOP + (logo_height + 30 if logo_height else 0)
    
    # Title
    title_lines = wrap_text(draw, title, title_font, max_text_width)
    line_h = title_font.getbbox("Ag")[3]
    height += len(title_lines) * (line_h + 8) + 10
    
    # Sections
    for sec in sections:
        heading_lines = wrap_text(draw, sec["heading"], section_font, max_text_width)
        heading_h = section_font.getbbox("Ag")[3]
        height += len(heading_lines) * (heading_h + 6) + 6
        
        body_h = body_font.getbbox("Ag")[3]
        for text in sec["lines"]:
            wrapped = wrap_text(draw, text, body_font, max_text_width)
            height += len(wrapped) * (body_h + 6)
        
        height += 12  # gap between sections
    
    return height


def render_post_image(title: str, sections: List[Dict[str, Any]], out_path: str) -> str:
    """
    sections: list of {"heading": str, "lines": [str, ...]}
    """
    im = Image.new("RGB", (IMG_W, IMG_H), BG_COLOR)
    draw = ImageDraw.Draw(im)

    # ---- Logo at top-left ----
    logo = load_logo()
    logo_height = 0
    if logo is not None:
        im.paste(logo, (MARGIN_X, MARGIN_TOP), logo)
        _, logo_height = logo.size

    max_text_width = IMG_W - 2 * MARGIN_X
    available_height = IMG_H - MARGIN_TOP - MARGIN_BOTTOM - (logo_height + 30 if logo_height else 0)
    
    # Try different font sizes until content fits
    title_sizes = [56, 48, 42, 36]
    section_sizes = [40, 36, 32, 28]
    body_sizes = [32, 28, 26, 24]
    
    best_fonts = None
    for t_size, s_size, b_size in zip(title_sizes, section_sizes, body_sizes):
        title_font = load_font(["DejaVuSans-Bold.ttf", "Arial.ttf"], t_size)
        section_font = load_font(["DejaVuSans-Bold.ttf", "Arial.ttf"], s_size)
        body_font = load_font(["DejaVuSans.ttf", "Arial.ttf"], b_size)
        
        content_height = calculate_content_height(draw, title, sections, title_font, 
                                                  section_font, body_font, max_text_width, logo_height)
        
        if content_height <= IMG_H - MARGIN_BOTTOM:
            best_fonts = (title_font, section_font, body_font)
            break
    
    # Fallback to smallest size if nothing fits
    if best_fonts is None:
        best_fonts = (
            load_font(["DejaVuSans-Bold.ttf", "Arial.ttf"], title_sizes[-1]),
            load_font(["DejaVuSans-Bold.ttf", "Arial.ttf"], section_sizes[-1]),
            load_font(["DejaVuSans.ttf", "Arial.ttf"], body_sizes[-1])
        )
    
    title_font, section_font, body_font = best_fonts

    # ---- Title under logo ----
    title_x = MARGIN_X
    title_y = MARGIN_TOP + (logo_height + 30 if logo_height else 0)

    title_lines = wrap_text(draw, title, title_font, max_text_width)
    for line in title_lines:
        draw.text((title_x, title_y), line, font=title_font, fill=HEADING_COLOR)
        line_h = title_font.getbbox("Ag")[3]
        title_y += line_h + 8

    y = title_y + 10  # start of content below title

    # ---- Sections ----
    for sec in sections:
        heading = sec["heading"]
        lines = sec["lines"]

        # Heading (gold)
        heading_lines = wrap_text(draw, heading, section_font, max_text_width)
        for hl in heading_lines:
            if y > IMG_H - MARGIN_BOTTOM:
                break
            draw.text((MARGIN_X, y), hl, font=section_font, fill=HEADING_COLOR)
            line_h = section_font.getbbox("Ag")[3]
            y += line_h + 6
        y += 6  # extra space after heading

        # Body lines (white)
        for text in lines:
            wrapped = wrap_text(draw, text, body_font, max_text_width)
            for wline in wrapped:
                line_h = body_font.getbbox("Ag")[3]
                if y > IMG_H - MARGIN_BOTTOM - line_h:
                    # no more vertical space
                    break
                draw.text((MARGIN_X, y), wline, font=body_font, fill=BODY_COLOR)
                y += line_h + 6
            else:
                # inner loop didn't break
                continue
            # inner loop broke, stop drawing further lines/sections
            break

        y += 12  # gap between sections
        if y > IMG_H - MARGIN_BOTTOM:
            break

    im.save(out_path)
    print("Saved image:", out_path)
    return out_path


# ----------------- Email -----------------
def send_email(image_paths: List[str], target_date: datetime.date) -> None:
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise RuntimeError("Email credentials not set in environment")

    msg = EmailMessage()
    msg["Subject"] = f"Racing Graphics for {target_date.strftime('%d %b %Y')}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS

    if image_paths:
        msg.set_content(
            f"Attached are the social graphics for all meetings on {target_date.strftime('%d %b %Y')}."
        )
    else:
        msg.set_content(
            f"No meetings were found in the XML files for {target_date.strftime('%d %b %Y')}."
        )

    for path in image_paths:
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
    print("Email sent with", len(image_paths), "attachments")


# ----------------- Build content for posts -----------------
def build_posts_for_meeting(meeting: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Returns list of posts; each post is {"title": str, "sections": [...]}
    """
    meeting_name = meeting["meeting_name"]

    # Helpers
    def trainer_line(item: Dict[str, str]) -> str:
        rank_str = ordinal(item.get("rank", ""))
        name = item.get("name", "")
        wins = item.get("wins", "")
        runs = item.get("runs", "")
        sr = item.get("strikeRate", "")
        return f"{rank_str} {name} – {sr}% strike rate ({wins} wins from {runs} runners)"

    def jockey_line(item: Dict[str, str]) -> str:
        rank_str = ordinal(item.get("rank", ""))
        name = item.get("name", "")
        wins = item.get("wins", "")
        runs = item.get("runs", "")
        sr = item.get("strikeRate", "")
        return f"{rank_str} {name} – {sr}% strike rate ({wins} wins from {runs} rides)"

    # Post 1: Top track trainers/jockeys (last 5 years)
    sections1: List[Dict[str, Any]] = []
    if meeting["top_track_trainers"]:
        sections1.append({
            "heading": "Top Track Trainers – Last 5 Years",
            "lines": [trainer_line(it) for it in meeting["top_track_trainers"]],
        })
    if meeting["top_track_jockeys"]:
        sections1.append({
            "heading": "Top Track Jockeys – Last 5 Years",
            "lines": [jockey_line(it) for it in meeting["top_track_jockeys"]],
        })

    # Post 2: Hot trainers/jockeys (last month)
    sections2: List[Dict[str, Any]] = []
    if meeting["hot_trainers"]:
        sections2.append({
            "heading": "Hot Trainers (Last Month)",
            "lines": [trainer_line(it) for it in meeting["hot_trainers"]],
        })
    if meeting["hot_jockeys"]:
        sections2.append({
            "heading": "Hot Jockeys (Last Month)",
            "lines": [jockey_line(it) for it in meeting["hot_jockeys"]],
        })

    # Post 3: Dropping in class + well handicapped
    sections3: List[Dict[str, Any]] = []
    drop = meeting["drop_runners"]
    won = meeting["won_runners"]

    if drop:
        lines = []
        for r in drop:
            name = r.get("name", "")
            time = r.get("raceTime", "")
            if time:
                lines.append(f"{name} running in the {time}")
            else:
                lines.append(name)
        sections3.append({
            "heading": "Horses Dropping in Class",
            "lines": lines,
        })

    if won:
        lines = []
        for r in won:
            name = r.get("name", "")
            time = r.get("raceTime", "")
            diff = r.get("diff", "")
            if diff:
                lines.append(f"{name} won off a {diff}lb higher mark – runs in the {time} today")
            else:
                lines.append(f"{name} – runs in the {time} today")
        sections3.append({
            "heading": "Well Handicapped Horses",
            "lines": lines,
        })

    posts: List[Dict[str, Any]] = []
    if sections1:
        posts.append({
            "title": meeting_name,
            "sections": sections1,
        })
    if sections2:
        posts.append({
            "title": meeting_name,
            "sections": sections2,
        })
    if sections3:
        posts.append({
            "title": meeting_name,
            "sections": sections3,
        })
    return posts


# ----------------- Main -----------------
def main():
    # Target = TOMORROW'S meetings (for 10AM run)
    today = datetime.datetime.utcnow().date()
    target_date = today + datetime.timedelta(days=1)
    print("Preparing graphics for date:", target_date)

    xml_paths = download_xml_files(target_date)
    meetings: Dict[str, Dict[str, Any]] = {}

    for path in xml_paths:
        print("Parsing", path)
        try:
            meeting = parse_meeting_file(path, target_date)
        except Exception as e:
            print("  -> parse failed:", e)
            continue
        if not meeting:
            continue
        key = f"{meeting['tla']}_{meeting['date'].isoformat()}"
        # keep first per meeting key (5- files come first due to sorting)
        if key not in meetings:
            meetings[key] = meeting

    if not meetings:
        print("No meetings found for target date.")
        send_email([], target_date)
        return

    image_paths: List[str] = []
    for key, meeting in meetings.items():
        posts = build_posts_for_meeting(meeting)
        for idx, post in enumerate(posts, start=1):
            filename = f"{meeting['tla']}_{target_date.strftime('%d%m')}_post{idx}.png"
            out_path = os.path.join(OUT_DIR, filename)
            render_post_image(post["title"], post["sections"], out_path)
            image_paths.append(out_path)

    send_email(image_paths, target_date)


if __name__ == "__main__":
    main()
