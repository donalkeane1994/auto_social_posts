import os
import ftplib
import io
import smtplib
import ssl
from email.message import EmailMessage
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

FTP_SERVER = os.environ.get("FTP_SERVER")
FTP_USER = os.environ.get("FTP_USER")
FTP_PASS = os.environ.get("FTP_PASS")

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

# -----------------------------------------------------
# STEP 1 — DOWNLOAD *ALL* XML FILES FOR TODAY
# -----------------------------------------------------
def download_all_xml():
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()

    xml_files = [f for f in files if f.endswith(".xml")]

    downloaded = []
    for filename in xml_files:
        data = io.BytesIO()
        ftp.retrbinary(f"RETR {filename}", data.write)
        data.seek(0)

        local_path = f"{OUT_DIR}/{filename}"
        with open(local_path, "wb") as f:
            f.write(data.getvalue())

        downloaded.append(local_path)

    ftp.quit()
    return downloaded

# -----------------------------------------------------
# STEP 2 — PARSE A SINGLE XML FILE
# -----------------------------------------------------
def parse_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    meeting = root.find("Meeting")
    meeting_name = meeting.attrib.get("name", "Unknown Meeting")

    stats = meeting.find("MiscStatistics")
    topx = stats.find("TopXStatistics")

    # helper to get jockey/trainer lists
    def get_list(name):
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == name:
                return s.findall("Statistic")[:5]
        return []

    data = {
        "meeting": meeting_name,
        "top_track_jockeys": get_list("TopTrackJockeys"),
        "hot_jockeys": get_list("HotJockeys"),
        "top_track_trainers": get_list("TopTrackTrainers"),
        "hot_trainers": get_list("HotTrainers"),
    }

    # dropping in class
    drop_nodes = stats.find("RunnerDropInClass")
    data["drop"] = drop_nodes.findall("Runner") if drop_nodes is not None else []

    # well handicapped
    won_nodes = stats.find("WonOffHigherHandicap")
    won = won_nodes.findall("Runner") if won_nodes is not None else []
    data["won"] = won[:5]

    return data

# -----------------------------------------------------
# STEP 3 — RENDERS FOR POST 1 & POST 2
# -----------------------------------------------------
def render_post1(data, prefix):
    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    y = 40
    draw.text((40, y), f"{data['meeting']} – Top Jockeys & Trainers", font=font, fill="black")
    y += 60

    for title, items in [
        ("Top Track Jockeys", data["top_track_jockeys"]),
        ("Hot Jockeys", data["hot_jockeys"]),
        ("Top Track Trainers", data["top_track_trainers"]),
        ("Hot Trainers", data["hot_trainers"]),
    ]:
        draw.text((40, y), title, font=font, fill="black")
        y += 30
        for i in items:
            draw.text(
                (40, y),
                f"{i.attrib.get('rank')}. {i.attrib.get('name')} ({i.attrib.get('wins')}/{i.attrib.get('runs')})",
                font=font, fill="gray"
            )
            y += 25
        y += 20

    out = f"{OUT_DIR}/{prefix}_post1.png"
    img.save(out)
    return out


def render_post2(data, prefix):
    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    y = 40
    draw.text((40, y), f"{data['meeting']} – Dropping & Handicapped", font=font, fill="black")
    y += 60

    draw.text((40, y), "Dropping in Class:", font=font, fill="black")
    y += 30
    for r in data["drop"][:10]:
        draw.text(
            (40, y),
            f"• {r.attrib.get('name')} ({r.attrib.get('raceTime')})",
            font=font,
            fill="gray"
        )
        y += 25

    y += 40
    draw.text((40, y), "Well Handicapped:", font=font, fill="black")
    y += 30
    for r in data["won"]:
        draw.text(
            (40, y),
            f"• {r.attrib.get('name')} ({r.attrib.get('raceTime')})",
            font=font,
            fill="gray"
        )
        y += 25

    out = f"{OUT_DIR}/{prefix}_post2.png"
    img.save(out)
    return out

# -----------------------------------------------------
# STEP 4 — EMAIL ALL IMAGES TOGETHER
# -----------------------------------------------------
def send_email(images):
    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics (All Meetings)"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached (all meetings).")

    for path in images:
        with open(path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="image",
                subtype="png",
                filename=os.path.basename(path)
            )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

# -----------------------------------------------------
# MAIN
# -----------------------------------------------------
def main():
    xml_files = download_all_xml()

    all_images = []

    for xml_path in xml_files:
        data = parse_xml(xml_path)

        # Make safe filename version
        prefix = data["meeting"].replace(" ", "_")

        p1 = render_post1(data, prefix)
        p2 = render_post2(data, prefix)

        all_images.extend([p1, p2])

    # send ONE email containing ALL images
    send_email(all_images)

    print("Email sent with", len(all_images), "images!")

if __name__ == "__main__":
    main()
