from PIL import Image, ImageDraw, ImageFont

BG_COLOR = "#1F2A4D"      # Deep navy
HEAD_COLOR = "#FFBA00"    # Gold
TEXT_COLOR = "#FFFFFF"    # White

TITLE_FONT = ImageFont.truetype("DejaVuSans-Bold.ttf", 70)
HEAD_FONT  = ImageFont.truetype("DejaVuSans-Bold.ttf", 50)
BODY_FONT  = ImageFont.truetype("DejaVuSans.ttf", 42)

def load_logo():
    try:
        logo = Image.open("logo.png").convert("RGBA")
        # scale larger (A = bigger vertical footprint)
        w, h = logo.size
        scale = 0.55  # increase this if you want even bigger
        logo = logo.resize((int(w * scale), int(h * scale)))
        return logo
    except:
        return None


def draw_heading(draw, text, y):
    draw.text((60, y), text, font=HEAD_FONT, fill=HEAD_COLOR)
    return y + 80


def draw_body(draw, text, y):
    draw.text((60, y), text, font=BODY_FONT, fill=TEXT_COLOR)
    return y + 60



# ---------------------------------------------------------
#   POST 1 — Top Track Trainers & Top Track Jockeys
# ---------------------------------------------------------
def render_post1(meeting_name, tt_trainers, tt_jockeys):
    img = Image.new("RGB", (1080, 1350), BG_COLOR)
    draw = ImageDraw.Draw(img)

    logo = load_logo()
    if logo:
        img.paste(logo, (60, 40), logo)

    y = 180  # push content below the logo

    # Title
    title = f"Top Track Stats – {meeting_name}"
    draw.text((60, y), title, font=TITLE_FONT, fill=HEAD_COLOR)
    y += 120

    # --- Trainers ---
    y = draw_heading(draw, f"Top Track Trainers – Last 5 Years", y)
    for s in tt_trainers[:5]:
        rank = s.attrib["rank"]
        name = s.attrib["name"]
        sr = s.attrib["strikeRate"]
        wins = s.attrib["wins"]
        runs = s.attrib["runs"]
        line = f"{rank}st  {name}  {sr}% SR  ({wins} wins from {runs})"
        y = draw_body(draw, line, y)

    y += 40

    # --- Jockeys ---
    y = draw_heading(draw, f"Top Track Jockeys – Last 5 Years", y)
    for s in tt_jockeys[:5]:
        rank = s.attrib["rank"]
        name = s.attrib["name"]
        sr = s.attrib["strikeRate"]
        wins = s.attrib["wins"]
        runs = s.attrib["runs"]
        line = f"{rank}st  {name}  {sr}% SR  ({wins} wins from {runs})"
        y = draw_body(draw, line, y)

    out = f"{OUT_DIR}/{meeting_name}_post1.png"
    img.save(out)
    return out



# ---------------------------------------------------------
#   POST 2 — Hot Trainers & Hot Jockeys
# ---------------------------------------------------------
def render_post2(meeting_name, hot_trainers, hot_jockeys):
    img = Image.new("RGB", (1080, 1350), BG_COLOR)
    draw = ImageDraw.Draw(img)

    logo = load_logo()
    if logo:
        img.paste(logo, (60, 40), logo)

    y = 180

    title = f"Hot Form – {meeting_name}"
    draw.text((60, y), title, font=TITLE_FONT, fill=HEAD_COLOR)
    y += 120

    # --- Hot Trainers ---
    y = draw_heading(draw, "Hot Trainers – Last Month", y)
    for s in hot_trainers[:5]:
        rank = s.attrib["rank"]
        name = s.attrib["name"]
        sr = s.attrib["strikeRate"]
        wins = s.attrib["wins"]
        runs = s.attrib["runs"]
        line = f"{rank}st  {name}  {sr}% SR  ({wins} wins from {runs})"
        y = draw_body(draw, line, y)

    y += 40

    # --- Hot Jockeys ---
    y = draw_heading(draw, "Hot Jockeys – Last Month", y)
    for s in hot_jockeys[:5]:
        rank = s.attrib["rank"]
        name = s.attrib["name"]
        sr = s.attrib["strikeRate"]
        wins = s.attrib["wins"]
        runs = s.attrib["runs"]
        line = f"{rank}st  {name}  {sr}% SR  ({wins} wins from {runs})"
        y = draw_body(draw, line, y)

    out = f"{OUT_DIR}/{meeting_name}_post2.png"
    img.save(out)
    return out



# ---------------------------------------------------------
#   POST 3 — Dropping in Class / Well Handicapped
# ---------------------------------------------------------
def render_post3(meeting_name, dropping, handicapped):
    img = Image.new("RGB", (1080, 1350), BG_COLOR)
    draw = ImageDraw.Draw(img)

    logo = load_logo()
    if logo:
        img.paste(logo, (60, 40), logo)

    y = 180

    title = f"Today's Angles – {meeting_name}"
    draw.text((60, y), title, font=TITLE_FONT, fill=HEAD_COLOR)
    y += 120

    # Dropping in Class
    y = draw_heading(draw, "Dropping in Class Today", y)
    if not dropping:
        y = draw_body(draw, "No horses dropping in class today.", y)
    else:
        for r in dropping:
            name = r.attrib["name"]
            time = r.attrib["raceTime"]
            y = draw_body(draw, f"{name} – runs at {time}", y)

    y += 40

    # Well Handicapped
    y = draw_heading(draw, "Well Handicapped Today", y)
    if not handicapped:
        y = draw_body(draw, "No well-handicapped horses today.", y)
    else:
        for r in handicapped:
            name = r.attrib["name"]
            time = r.attrib["raceTime"]
            weight_then = r.find("Weight").attrib.get("weightThen", "")
            weight_now = r.find("Weight").attrib.get("weightNow", "")
            diff = int(weight_then) - int(weight_now)
            y = draw_body(draw, f"{name} – won off {diff}lbs higher, runs at {time}", y)

    out = f"{OUT_DIR}/{meeting_name}_post3.png"
    img.save(out)
    return out
