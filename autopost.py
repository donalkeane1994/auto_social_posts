import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

#############################
# Emoji ranking
#############################
RANK_EMOJI = {
    "1": "🥇",
    "2": "🥈",
    "3": "🥉",
    "4": "4️⃣",
    "5": "5️⃣"
}

#############################
# Colours & fonts
#############################
BG = (31, 42, 77)        # deep navy
WHITE = (255, 255, 255)
GOLD = (255, 186, 0)

TITLE_FONT = ImageFont.truetype("arial.ttf", 65)
SUB_FONT = ImageFont.truetype("arial.ttf", 45)
TEXT_FONT = ImageFont.truetype("arial.ttf", 38)

#############################
# Download ALL xml files for tomorrow
#############################
def download_tomorrow_files():
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%d%m")
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)

    files = ftp.nlst()
    xmls = [f for f in files if f.endswith(".xml") and f[-8:-4] == tomorrow]

    meetings = []

    for filename in xmls:
        bio = io.BytesIO()
        ftp.retrbinary(f"RETR {filename}", bio.write)
        path = f"{OUT_DIR}/{filename}"
        with open(path, "wb") as f:
            f.write(bio.getvalue())
        meetings.append(path)

    ftp.quit()
    return meetings

#############################
# Parse meeting XML
#############################
def parse_meeting(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    name = meeting.attrib.get("name")

    stats = meeting.find("MiscStatistics")
    topx = stats.find("TopXStatistics")

    def get_list(stat_type):
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == stat_type:
                return s.findall("Statistic")[:5]
        return []

    return {
        "course_name": name,
        "top_tr_tr": get_list("TopTrackTrainers"),
        "top_tr_jk": get_list("TopTrackJockeys"),
        "hot_tr": get_list("HotTrainers"),
        "hot_jk": get_list("HotJockeys"),
        "drop": stats.findall("RunnerDropInClass/Runner"),
        "won": stats.findall("WonOffHigherHandicap/Runner")[:5]
    }

#############################
# Draw post1 template
#############################
def render_post1(data, logo):
    img = Image.new("RGB", (1080, 1350), BG)
    d = ImageDraw.Draw(img)

    # logo
    img.paste(logo, (40, 40), mask=logo)

    y = 180
    title = f"{data['course_name']} – Jockeys & Trainers"
    d.text((40, y), title, font=TITLE_FONT, fill=WHITE)
    y += 110

    def block(header, items):
        nonlocal y
        d.text((40, y), header, font=SUB_FONT, fill=GOLD)
        y += 70
        for s in items:
            rank = s.attrib.get("rank")
            wins = s.attrib.get("wins")
            runs = s.attrib.get("runs")
            sr = s.attrib.get("strikeRate")
            name = s.attrib.get("name")

            line = f"{RANK_EMOJI.get(rank, rank)} {name} {sr}% SR ({wins} wins from {runs})"
            d.text((40, y), line, font=TEXT_FONT, fill=WHITE)
            y += 55
        y += 40

    block("Top Track Trainers – Last 5 Years", data["top_tr_tr"])
    block("Top Track Jockeys – Last 5 Years", data["top_tr_jk"])
    block("Hot Trainers – Last Month", data["hot_tr"])
    block("Hot Jockeys – Last Month", data["hot_jk"])

    out = f"{OUT_DIR}/{data['course_name']}_post1.png"
    img.save(out)
    return out

#############################
# Draw post2 template
#############################
def render_post2(data, logo):
    img = Image.new("RGB", (1080, 1350), BG)
    d = ImageDraw.Draw(img)

    img.paste(logo, (40, 40), mask=logo)

    y = 180
    title = f"{data['course_name']} – Horses to Note"
    d.text((40, y), title, font=TITLE_FONT, fill=WHITE)
    y += 110

    # Dropping in class
    d.text((40, y), "Dropping In Class Today", font=SUB_FONT, fill=GOLD)
    y += 70

    for r in data["drop"]:
        name = r.attrib["name"]
        time = r.attrib["raceTime"]
        d.text((40, y), f"• {name} running at {time}", font=TEXT_FONT, fill=WHITE)
        y += 55

    y += 60

    # Well handicapped today
    d.text((40, y), "Well Handicapped Today", font=SUB_FONT, fill=GOLD)
    y += 70

    for r in data["won"]:
        name = r.attrib["name"]
        time = r.attrib["raceTime"]
        weight_now = r.find("Weight").attrib.get("weightNow")
        weight_then = r.find("Weight").attrib.get("weightThen")
        diff = int(weight_then) - int(weight_now)

        line = f"• {name} won off {diff}lbs higher – runs at {time}"
        d.text((40, y), line, font=TEXT_FONT, fill=WHITE)
        y += 55

    out = f"{OUT_DIR}/{data['course_name']}_post2.png"
    img.save(out)
    return out

#############################
# Email images
#############################
def send_email(images):
    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Attached – all today's meeting graphics.")

    for path in images:
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype="png", filename=os.path.basename(path))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

#############################
# Main
#############################
def main():
    xmls = download_tomorrow_files()
    if not xmls:
        print("No files for tomorrow.")
        return

    # load logo
    logo = Image.open("logo.png").convert("RGBA")
    logo = logo.resize((180, 180))

    all_images = []

    for xml in xmls:
        data = parse_meeting(xml)
        p1 = render_post1(data, logo)
        p2 = render_post2(data, logo)
        all_images.append(p1)
        all_images.append(p2)

    send_email(all_images)
    print("Email sent!")

if __name__ == "__main__":
    main()
