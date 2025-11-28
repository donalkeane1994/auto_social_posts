import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ----------- ENV / SECRETS -----------
FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

# ----------- HELPERS -----------

def get_tomorrow_date():
    # GitHub runners use UTC; for UK racing this is fine
    today_utc = datetime.utcnow().date()
    return today_utc + timedelta(days=1)

def fetch_tomorrows_meetings_from_ftp():
    """Return a list of dicts, one per meeting taking place tomorrow."""
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()
    xml_files = [f for f in files if f.lower().endswith(".xml")]

    tomorrow = get_tomorrow_date()
    meetings = []

    for filename in xml_files:
        bio = io.BytesIO()
        try:
            ftp.retrbinary(f"RETR {filename}", bio.write)
        except Exception as e:
            print(f"Skipping {filename} (FTP error): {e}")
            continue

        bio.seek(0)
        try:
            tree = ET.parse(bio)
        except ET.ParseError:
            print(f"Skipping {filename} (parse error)")
            continue

        root = tree.getroot()
        meeting_el = root.find("Meeting")
        if meeting_el is None:
            continue

        date_str = meeting_el.attrib.get("date", "")  # e.g. "29/11/2025"
        try:
            meeting_date = datetime.strptime(date_str, "%d/%m/%Y").date()
        except ValueError:
            print(f"Skipping {filename} (bad date {date_str})")
            continue

        if meeting_date != tomorrow:
            continue

        meeting_data = parse_meeting(root)
        if meeting_data:
            meeting_data["source_filename"] = filename
            meetings.append(meeting_data)

    ftp.quit()
    print(f"Found {len(meetings)} meetings for tomorrow ({tomorrow})")
    return meetings

def parse_meeting(root):
    meeting = root.find("Meeting")
    if meeting is None:
        return None

    stats = meeting.find("MiscStatistics")
    if stats is None:
        return None

    topx = stats.find("TopXStatistics")
    if topx is None:
        return None

    course = meeting.find("Course")
    meeting_name = meeting.attrib.get("name", "").strip()
    meeting_date = meeting.attrib.get("date", "")
    course_tla = course.attrib.get("tla", "").strip() if course is not None else ""

    def get_list(statistic_type):
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == statistic_type:
                return s.findall("Statistic")[:5]
        return []

    top_track_jockeys = get_list("TopTrackJockeys")
    hot_jockeys = get_list("HotJockeys")
    top_track_trainers = get_list("TopTrackTrainers")
    hot_trainers = get_list("HotTrainers")

    drop_section = stats.find("RunnerDropInClass")
    drop_runners = drop_section.findall("Runner") if drop_section is not None else []

    won_section = stats.find("WonOffHigherHandicap")
    won_runners = won_section.findall("Runner") if won_section is not None else []
    won_runners = won_runners[:5]

    return {
        "meeting_name": meeting_name,
        "meeting_date_str": meeting_date,
        "course_tla": course_tla,
        "top_track_jockeys": top_track_jockeys,
        "hot_jockeys": hot_jockeys,
        "top_track_trainers": top_track_trainers,
        "hot_trainers": hot_trainers,
        "drop_runners": drop_runners,
        "won_runners": won_runners,
    }

# ----------- RENDERING -----------

def render_post1(meeting_data):
    """Post 1: Top Track Jockeys/Trainers + Hot Jockeys/Trainers for this course."""
    meeting_name = meeting_data["meeting_name"]
    tla = meeting_data["course_tla"] or meeting_name.replace(" ", "")

    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font_big = ImageFont.load_default()
    font = ImageFont.load_default()

    y = 40
    # Heading: course name
    draw.text((40, y), meeting_name, font=font_big, fill="black")
    y += 40

    sections = [
        (f"Top Track Jockeys @ {meeting_name}", meeting_data["top_track_jockeys"]),
        ("Hot Jockeys", meeting_data["hot_jockeys"]),
        (f"Top Track Trainers @ {meeting_name}", meeting_data["top_track_trainers"]),
        ("Hot Trainers", meeting_data["hot_trainers"]),
    ]

    for title, items in sections:
        draw.text((40, y), title, font=font, fill="black")
        y += 25
        for i in items:
            name = i.attrib.get("name")
            rank = i.attrib.get("rank")
            wins = i.attrib.get("wins")
            runs = i.attrib.get("runs")
            line = f"{rank}. {name} ({wins}/{runs})"
            draw.text((40, y), line, font=font, fill="gray")
            y += 20
        y += 15

    out_path = os.path.join(OUT_DIR, f"{tla}_post1.png")
    img.save(out_path)
    return out_path

def render_post2(meeting_data):
    """Post 2: Dropping in Class + Well Handicapped for this course."""
    meeting_name = meeting_data["meeting_name"]
    tla = meeting_data["course_tla"] or meeting_name.replace(" ", "")

    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font_big = ImageFont.load_default()
    font = ImageFont.load_default()

    y = 40
    # Heading: course name
    draw.text((40, y), meeting_name, font=font_big, fill="black")
    y += 40

    # Dropping in class section
    draw.text((40, y), f"Runners at {meeting_name} Dropping in Class", font=font, fill="black")
    y += 25
    for r in meeting_data["drop_runners"][:10]:
        name = r.attrib.get("name")
        race_time = r.attrib.get("raceTime")
        line = f"• {name} ({race_time})"
        draw.text((40, y), line, font=font, fill="gray")
        y += 20

    y += 30
    # Well handicapped section
    draw.text((40, y), f"Well Handicapped Horses running today at {meeting_name}", font=font, fill="black")
    y += 25
    for r in meeting_data["won_runners"]:
        name = r.attrib.get("name")
        race_time = r.attrib.get("raceTime")
        line = f"• {name} ({race_time})"
        draw.text((40, y), line, font=font, fill="gray")
        y += 20

    out_path = os.path.join(OUT_DIR, f"{tla}_post2.png")
    img.save(out_path)
    return out_path

# ----------- EMAIL SENDING -----------

def send_email_with_images(image_paths, tomorrow_date):
    msg = EmailMessage()
    msg["Subject"] = f"Tomorrow's racing graphics ({tomorrow_date.strftime('%d/%m/%Y')})"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached (two posts per meeting).")

    for path in image_paths:
        with open(path, "rb") as f:
            img_data = f.read()
        filename = os.path.basename(path)
        msg.add_attachment(img_data, maintype="image", subtype="png", filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

# ----------- MAIN -----------

def main():
    tomorrow = get_tomorrow_date()
    meetings = fetch_tomorrows_meetings_from_ftp()

    if not meetings:
        print("No meetings found for tomorrow.")
        return

    all_images = []
    for m in meetings:
        p1 = render_post1(m)
        p2 = render_post2(m)
        all_images.extend([p1, p2])

    send_email_with_images(all_images, tomorrow)
    print(f"Email sent with {len(all_images)} images for {len(meetings)} meetings.")

if __name__ == "__main__":
    main()
