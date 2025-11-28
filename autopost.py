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

LOCAL_XML = "meeting.xml"
OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)

def download_xml():
    ftp = ftplib.FTP(FTP_SERVER)
    ftp.login(FTP_USER, FTP_PASS)
    files = ftp.nlst()
    xml_files = [f for f in files if f.endswith(".xml")]
    if not xml_files:
        raise Exception("No XML found on FTP")

    filename = xml_files[0]
    bio = io.BytesIO()
    ftp.retrbinary(f"RETR {filename}", bio.write)
    ftp.quit()

    with open(LOCAL_XML, "wb") as f:
        f.write(bio.getvalue())

    return LOCAL_XML

def parse_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    meeting = root.find("Meeting")
    stats = meeting.find("MiscStatistics")
    topx = stats.find("TopXStatistics")

    def get_list(name):
        for s in topx.findall("TopXStatistic"):
            if s.attrib.get("statisticType") == name:
                return s.findall("Statistic")[:5]
        return []

    top_track_jockeys = get_list("TopTrackJockeys")
    hot_jockeys = get_list("HotJockeys")
    top_track_trainers = get_list("TopTrackTrainers")
    hot_trainers = get_list("HotTrainers")

    drop_nodes = stats.find("RunnerDropInClass")
    drop = drop_nodes.findall("Runner") if drop_nodes is not None else []

    won_nodes = stats.find("WonOffHigherHandicap")
    won = won_nodes.findall("Runner") if won_nodes is not None else []
    won = won[:5]

    return {
        "top_track_jockeys": top_track_jockeys,
        "hot_jockeys": hot_jockeys,
        "top_track_trainers": top_track_trainers,
        "hot_trainers": hot_trainers,
        "drop": drop,
        "won": won
    }

def render_post1(data):
    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    y = 40
    draw.text((40, y), "Top Jockeys & Trainers", font=font, fill="black")
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
            name = i.attrib.get("name")
            rank = i.attrib.get("rank")
            wins = i.attrib.get("wins")
            runs = i.attrib.get("runs")
            draw.text((40, y), f"{rank}. {name} ({wins}/{runs})", font=font, fill="gray")
            y += 25
        y += 20

    out = f"{OUT_DIR}/post1.png"
    img.save(out)
    return out

def render_post2(data):
    img = Image.new("RGB", (1080, 1080), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    y = 40
    draw.text((40, y), "Dropping in Class & Well Handicapped", font=font, fill="black")
    y += 60

    draw.text((40, y), "Dropping in Class:", font=font, fill="black")
    y += 30
    for r in data["drop"][:10]:
        draw.text((40, y), f"• {r.attrib.get('name')} ({r.attrib.get('raceTime')})", font=font, fill="gray")
        y += 25

    y += 40
    draw.text((40, y), "Well Handicapped:", font=font, fill="black")
    y += 30
    for r in data["won"]:
        draw.text((40, y), f"• {r.attrib.get('name')} ({r.attrib.get('raceTime')})", font=font, fill="gray")
        y += 25

    out = f"{OUT_DIR}/post2.png"
    img.save(out)
    return out

def send_email_with_images(img1, img2):
    msg = EmailMessage()
    msg["Subject"] = "Daily Racing Graphics"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg.set_content("Your daily racing graphics are attached.")

    for path in [img1, img2]:
        with open(path, "rb") as f:
            img_data = f.read()
        msg.add_attachment(img_data, maintype="image", subtype="png", filename=os.path.basename(path))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

def main():
    xml_path = download_xml()
    data = parse_xml(xml_path)
    p1 = render_post1(data)
    p2 = render_post2(data)
    send_email_with_images(p1, p2)
    print("Email sent!")

if __name__ == "__main__":
    main()
