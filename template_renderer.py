import io, os, re, sys
from urllib.request import Request, urlopen
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

load_dotenv()
SUPABASE_URL=os.getenv("SUPABASE_URL")
SUPABASE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY: raise RuntimeError("Supabase environment variables are missing.")
supabase=create_client(SUPABASE_URL,SUPABASE_KEY)

W,H=1080,1350
HERO_H=620
STRIP_H=300
PANEL_Y=HERO_H+STRIP_H
WHITE="#FFFFFF"

def download_image(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 Nyro/1.0"})
    with urlopen(req,timeout=30) as r: data=r.read()
    return Image.open(io.BytesIO(data)).convert("RGBA")

def cover_crop(img,w,h):
    sw,sh=img.size
    scale=max(w/sw,h/sh)
    img=img.resize((round(sw*scale),round(sh*scale)),Image.Resampling.LANCZOS)
    left=max(0,(img.width-w)//2); top=max(0,(img.height-h)//2)
    return img.crop((left,top,left+w,top+h))

def paste_cover(canvas,img,box):
    l,t,r,b=box
    img=cover_crop(img,r-l,b-t)
    canvas.paste(img,(l,t),img)

def get_font(size,bold=False):
    paths = ([r"C:\Windows\Fonts\arialbd.ttf",r"C:\Windows\Fonts\segoeuib.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
             [r"C:\Windows\Fonts\arial.ttf",r"C:\Windows\Fonts\segoeui.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for p in paths:
        if os.path.exists(p): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def fit_font(draw,text,max_width,start_size,min_size=24,bold=False):
    text=str(text or "")
    for size in range(start_size,min_size-1,-2):
        f=get_font(size,bold)
        b=draw.textbbox((0,0),text,font=f)
        if b[2]-b[0] <= max_width: return f
    return get_font(min_size,bold)

def centered(draw,text,y,font,fill):
    b=draw.textbbox((0,0),str(text),font=font)
    draw.text(((W-(b[2]-b[0]))/2,y),str(text),font=font,fill=fill)

def load_property(pid):
    r=supabase.table("property_listings").select("*").eq("id",pid).single().execute()
    if not r.data: raise RuntimeError(f"Property {pid} could not be loaded.")
    return r.data

def load_images(pid):
    r=(supabase.table("property_images").select("stored_image_url,image_order")
       .eq("property_listing_id",pid).order("image_order").execute())
    return [x["stored_image_url"] for x in (r.data or []) if x.get("stored_image_url")]

def load_agency():
    r=supabase.table("agency_settings").select("*").order("id").limit(1).execute()
    if not r.data: raise RuntimeError("No agency_settings row found.")
    return r.data[0]

def format_price(price,listing_type):
    if price is None: return "Price on application"
    try: value=f"£{float(price):,.0f}"
    except (TypeError,ValueError): value=str(price)
    lt=str(listing_type or "").lower()
    return value+" PCM" if ("rent" in lt or "let" in lt) else value

def location_text(p):
    """
    BM Estates title format:
    Property For Sale Westminster Road, Stoneygate, LE2 | 4 Bedroom Detached through BM Estates

    Output:
    WESTMINSTER ROAD
    Stoneygate, LE2
    """
    raw = str(p.get("title") or "").strip()
    if not raw:
        return "NEW PROPERTY", ""

    # Everything before the pipe is the marketing location section.
    location_part = raw.split("|", 1)[0].strip()

    # Remove the known listing prefix.
    location_part = re.sub(
        r"^\s*Property\s+(?:For\s+Sale|To\s+Let|For\s+Rent|For\s+Lease)\s*",
        "",
        location_part,
        flags=re.I,
    ).strip(" ,-–—|")

    parts = [part.strip() for part in location_part.split(",") if part.strip()]
    if not parts:
        return "NEW PROPERTY", ""

    road = parts[0].upper()
    area = ", ".join(parts[1:])

    return road, area

def event_badge_text(event_type):
    labels = {
        "NEW_LISTING": "JUST LISTED",
        "PRICE_REDUCED": "PRICE REDUCED",
        "RELISTED": "BACK ON MARKET",
    }
    return labels.get(
        str(event_type or "").upper(),
        str(event_type or "").replace("_", " ").upper()
    )


def render_just_listed_01(property_id, agency, output_path=None, event_type="NEW_LISTING"):
    p=load_property(property_id)
    urls=load_images(property_id)
    a=agency
    if not urls: raise RuntimeError(f"Property {property_id} has no stored property images.")

    primary=a.get("primary_colour") or "#0054A6"
    secondary=a.get("secondary_colour") or "#00AEEF"
    canvas=Image.new("RGB",(W,H),WHITE)

    hero=download_image(urls[0])
    paste_cover(canvas,hero,(0,0,W,HERO_H))

    if len(urls)>=3:
        paste_cover(canvas,download_image(urls[1]),(0,HERO_H,W//2,PANEL_Y))
        paste_cover(canvas,download_image(urls[2]),(W//2,HERO_H,W,PANEL_Y))
        ImageDraw.Draw(canvas).rectangle((W//2-3,HERO_H,W//2+3,PANEL_Y),fill=WHITE)
    elif len(urls)==2:
        paste_cover(canvas,download_image(urls[1]),(0,HERO_H,W,PANEL_Y))
    else:
        paste_cover(canvas,hero,(0,HERO_H,W,PANEL_Y))

    d=ImageDraw.Draw(canvas)
    d.rectangle((0,PANEL_Y,W,H),fill=primary)

    bw,bh=430,88
    bl=(W-bw)//2; bt=PANEL_Y-44
    d.rounded_rectangle((bl,bt,bl+bw,bt+bh),radius=18,fill=secondary)
    badge=event_badge_text(event_type)
    bf=fit_font(d,badge,bw-50,52,30,True)
    b=d.textbbox((0,0),badge,font=bf)
    d.text(((W-(b[2]-b[0]))/2,bt+(bh-(b[3]-b[1]))/2-b[1]),badge,font=bf,fill=WHITE)

    line1,line2=location_text(p)
    price=format_price(p.get("price"),p.get("listing_type"))
    lf1=fit_font(d,line1,W-100,44,28,True)
    centered(d,line1,PANEL_Y+78,lf1,WHITE)
    if line2:
        lf2=fit_font(d,line2,W-120,30,22,False)
        centered(d,line2,PANEL_Y+132,lf2,WHITE)
        price_y=PANEL_Y+178
    else:
        price_y=PANEL_Y+145
    pf=fit_font(d,price,W-100,58,38,True)
    centered(d,price,price_y,pf,WHITE)

    if a.get("logo_url"):
        logo=download_image(a["logo_url"])
        logo.thumbnail((300,100),Image.Resampling.LANCZOS)
        card_w,card_h=390,130
        card=Image.new("RGBA",(card_w,card_h),WHITE)
        card.paste(logo,((card_w-logo.width)//2,(card_h-logo.height)//2),logo)
        canvas.paste(card,((W-card_w)//2,H-card_h-18),card)

    output_path=output_path or f"just_listed_{property_id}.png"
    canvas.save(output_path,"PNG",optimize=True)
    print(f"Generated: {os.path.abspath(output_path)}")
    return output_path



def render_just_listed_02(property_id, agency, output_path=None, event_type="NEW_LISTING"):
    """Full-photo Just Listed template with clean header and bottom overlay."""
    p=load_property(property_id); urls=load_images(property_id); a=agency
    if not urls:
        raise RuntimeError(f"Property {property_id} has no stored property images.")

    primary=a.get("primary_colour") or "#0054A6"
    canvas=Image.new("RGB",(W,H),"#F7F7F5")
    d=ImageDraw.Draw(canvas)

    # Header only; everything below is photography.
    m=62
    header_h=190

    badge=event_badge_text(event_type)
    bw,bh=310,92
    by=50
    d.rounded_rectangle((m,by,m+bw,by+bh),radius=18,fill=primary)
    # Fit longer status labels inside the existing badge without altering its layout.
    bf=fit_font(d,badge,bw-48,38,24,True)
    bb=d.textbbox((0,0),badge,font=bf)
    d.text(
        (m+(bw-(bb[2]-bb[0]))/2, by+(bh-(bb[3]-bb[1]))/2-bb[1]),
        badge,font=bf,fill=WHITE
    )

    road,area=location_text(p)
    rx=490
    rw=W-m-rx
    accent=a.get("secondary_colour") or "#00AEEF"
    d.rectangle((455,52,461,139),fill=accent)
    d.text((rx,54),road,font=fit_font(d,road,rw,38,27,True),fill="#151515")
    if area:
        d.text((rx,105),area,font=fit_font(d,area,rw,29,22,False),fill="#444444")

    # Full-width hero below header.
    # Crop slightly deeper than the visible region so bottom-edge source watermarks
    # are more likely to fall outside the final composition.
    photo_y=header_h
    photo_h=H-header_h
    source=download_image(urls[0])

    # Manual cover crop with a slight upward focal bias.
    sw,sh=source.size
    target_ratio=W/photo_h
    source_ratio=sw/sh
    if source_ratio > target_ratio:
        crop_w=int(sh*target_ratio)
        left=max(0,(sw-crop_w)//2)
        hero=source.crop((left,0,left+crop_w,sh))
    else:
        crop_h=int(sw/target_ratio)
        # Bias crop upward to help remove bottom-right source watermark.
        top=max(0,int((sh-crop_h)*0.18))
        if top+crop_h>sh:
            top=sh-crop_h
        hero=source.crop((0,top,sw,top+crop_h))

    hero=hero.resize((W,photo_h),Image.Resampling.LANCZOS).convert("RGB")
    canvas.paste(hero,(0,photo_y))

    # Dark gradient overlay at bottom for readable property information.
    overlay=Image.new("RGBA",(W,photo_h),(0,0,0,0))
    od=ImageDraw.Draw(overlay)
    gradient_h=390
    for i in range(gradient_h):
        # Strongest at bottom, fading smoothly upward.
        progress=i/(gradient_h-1)
        alpha=int(205*(progress**1.7))
        y=photo_h-gradient_h+i
        od.line((0,y,W,y),fill=(0,0,0,alpha))
    canvas_rgba=canvas.convert("RGBA")
    canvas_rgba.alpha_composite(overlay,(0,photo_y))
    canvas=canvas_rgba.convert("RGB")
    d=ImageDraw.Draw(canvas)

    # Property info over the image.
    price=format_price(p.get("price"),p.get("listing_type"))
    price_y=H-235
    d.text(
        (m,price_y),
        price,
        font=fit_font(d,price,560,66,44,True),
        fill=WHITE
    )

    pt=str(p.get("property_type") or "").strip()
    if pt:
        styled_pt=pt.upper()
        parts=styled_pt.split(" BEDROOM ",1)
        if len(parts)==2 and parts[0].isdigit():
            styled_pt=f"{parts[0]} BEDROOM  •  {parts[1]}"
        d.text(
            (m,price_y+76),
            styled_pt,
            font=fit_font(d,styled_pt,590,29,20,True),
            fill=WHITE
        )

    d.rectangle((m,price_y+128,m+105,price_y+134),fill=accent)

    # Smaller, softer square logo integrated into the bottom overlay.
    if a.get("logo_url"):
        logo=download_image(a["logo_url"])
        logo.thumbnail((145,145),Image.Resampling.LANCZOS)
        square=170
        card=Image.new("RGBA",(square,square),(255,255,255,224))
        card.paste(
            logo,
            ((square-logo.width)//2,(square-logo.height)//2),
            logo
        )
        canvas_rgba=canvas.convert("RGBA")
        canvas_rgba.alpha_composite(card,(W-m-square,H-62-square))
        canvas=canvas_rgba.convert("RGB")

    output_path=output_path or f"just_listed_{property_id}.png"
    canvas.save(output_path,"PNG",optimize=True)
    print(f"Generated: {os.path.abspath(output_path)}")
    return output_path


def render_just_listed_03(property_id, agency, output_path=None, event_type="NEW_LISTING"):
    """Blue-tinted full-photo Just Listed template."""
    p=load_property(property_id); urls=load_images(property_id); a=agency
    if not urls:
        raise RuntimeError(f"Property {property_id} has no stored property images.")

    primary=a.get("primary_colour") or "#0054A6"
    canvas=Image.new("RGB",(W,H),"#F7F7F5")
    d=ImageDraw.Draw(canvas)

    # Header only; everything below is photography.
    m=62
    header_h=190

    badge=event_badge_text(event_type)
    bw,bh=310,92
    by=50
    d.rounded_rectangle((m,by,m+bw,by+bh),radius=18,fill=primary)
    # Fit longer status labels inside the existing badge without altering its layout.
    bf=fit_font(d,badge,bw-48,38,24,True)
    bb=d.textbbox((0,0),badge,font=bf)
    d.text(
        (m+(bw-(bb[2]-bb[0]))/2, by+(bh-(bb[3]-bb[1]))/2-bb[1]),
        badge,font=bf,fill=WHITE
    )

    road,area=location_text(p)
    rx=490
    rw=W-m-rx
    accent=a.get("secondary_colour") or "#00AEEF"
    d.rectangle((455,52,461,139),fill=accent)
    d.text((rx,54),road,font=fit_font(d,road,rw,38,27,True),fill="#151515")
    if area:
        d.text((rx,105),area,font=fit_font(d,area,rw,29,22,False),fill="#444444")

    # Full-width hero below header.
    # Crop slightly deeper than the visible region so bottom-edge source watermarks
    # are more likely to fall outside the final composition.
    photo_y=header_h
    photo_h=H-header_h
    source=download_image(urls[0])

    # Manual cover crop with a slight upward focal bias.
    sw,sh=source.size
    target_ratio=W/photo_h
    source_ratio=sw/sh
    if source_ratio > target_ratio:
        crop_w=int(sh*target_ratio)
        left=max(0,(sw-crop_w)//2)
        hero=source.crop((left,0,left+crop_w,sh))
    else:
        crop_h=int(sw/target_ratio)
        # Bias crop upward to help remove bottom-right source watermark.
        top=max(0,int((sh-crop_h)*0.18))
        if top+crop_h>sh:
            top=sh-crop_h
        hero=source.crop((0,top,sw,top+crop_h))

    hero=hero.resize((W,photo_h),Image.Resampling.LANCZOS).convert("RGB")

    # Template 03: BM-blue cinematic tint.
    # Light tint over the whole photograph, strengthening toward the bottom.
    tinted=hero.convert("RGBA")
    blue_layer=Image.new("RGBA",(W,photo_h),(0,84,166,0))
    blue_draw=ImageDraw.Draw(blue_layer)

    for y in range(photo_h):
        progress=y/max(1,photo_h-1)
        alpha=int(22 + (72 * (progress ** 1.8)))
        blue_draw.line((0,y,W,y),fill=(0,84,166,alpha))

    tinted=Image.alpha_composite(tinted,blue_layer).convert("RGB")
    canvas.paste(tinted,(0,photo_y))

    # Dark gradient overlay at bottom for readable property information.
    overlay=Image.new("RGBA",(W,photo_h),(0,0,0,0))
    od=ImageDraw.Draw(overlay)
    gradient_h=390
    for i in range(gradient_h):
        # Strongest at bottom, fading smoothly upward.
        progress=i/(gradient_h-1)
        alpha=int(225*(progress**1.65))
        y=photo_h-gradient_h+i
        od.line((0,y,W,y),fill=(0,0,0,alpha))
    canvas_rgba=canvas.convert("RGBA")
    canvas_rgba.alpha_composite(overlay,(0,photo_y))
    canvas=canvas_rgba.convert("RGB")
    d=ImageDraw.Draw(canvas)

    # Property info over the image.
    price=format_price(p.get("price"),p.get("listing_type"))
    price_y=H-235
    d.text(
        (m,price_y),
        price,
        font=fit_font(d,price,560,66,44,True),
        fill=WHITE
    )

    pt=str(p.get("property_type") or "").strip()
    if pt:
        styled_pt=pt.upper()
        parts=styled_pt.split(" BEDROOM ",1)
        if len(parts)==2 and parts[0].isdigit():
            styled_pt=f"{parts[0]} BEDROOM  •  {parts[1]}"
        d.text(
            (m,price_y+76),
            styled_pt,
            font=fit_font(d,styled_pt,590,29,20,True),
            fill=WHITE
        )

    d.rectangle((m,price_y+128,m+105,price_y+134),fill=accent)

    # Template 03: restore the clean white logo card for readability.
    if a.get("logo_url"):
        logo=download_image(a["logo_url"]).convert("RGBA")
        logo.thumbnail((145,145),Image.Resampling.LANCZOS)

        square=170
        card=Image.new("RGBA",(square,square),(255,255,255,235))
        card.paste(
            logo,
            ((square-logo.width)//2,(square-logo.height)//2),
            logo
        )

        canvas_rgba=canvas.convert("RGBA")
        canvas_rgba.alpha_composite(card,(W-m-square,H-62-square))
        canvas=canvas_rgba.convert("RGB")

    output_path=output_path or f"just_listed_{property_id}.png"
    canvas.save(output_path,"PNG",optimize=True)
    print(f"Generated: {os.path.abspath(output_path)}")
    return output_path



def upload_marketing_asset(local_path, listing_event_id, property_id, template_key):
    """Upload a rendered graphic and record the exact asset used for this event."""
    if not listing_event_id:
        raise RuntimeError("listing_event_id is required to upload a marketing asset.")

    bucket = "marketing-assets"
    storage_path = f"{listing_event_id}/{template_key}.png"

    with open(local_path, "rb") as f:
        file_bytes = f.read()

    # Upsert means regenerating the same event/template replaces the old graphic
    # instead of creating duplicate files.
    supabase.storage.from_(bucket).upload(
        storage_path,
        file_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )

    public_url = supabase.storage.from_(bucket).get_public_url(storage_path)

    # Keep one current SOCIAL_GRAPHIC row per event. This also makes manual
    # regeneration safe while we are testing templates.
    (
        supabase.table("marketing_assets")
        .delete()
        .eq("listing_event_id", listing_event_id)
        .eq("asset_type", "SOCIAL_GRAPHIC")
        .execute()
    )

    row = {
        "listing_event_id": listing_event_id,
        "property_listing_id": property_id,
        "asset_type": "SOCIAL_GRAPHIC",
        "template_key": template_key,
        "storage_url": public_url,
    }
    result = supabase.table("marketing_assets").insert(row).execute()
    if not result.data:
        raise RuntimeError("Marketing asset uploaded but database record was not created.")

    print(f"Uploaded marketing asset: {public_url}")
    return result.data[0]


def render_and_store_marketing_asset(property_id, listing_event_id, event_type):
    """Render the agency-selected template, upload it, and persist its URL."""
    agency = load_agency()
    agency_id = agency.get("id")
    if not agency_id:
        raise RuntimeError("agency_settings row has no id.")

    template_key = load_selected_template(agency_id, event_type)
    renderer = TEMPLATE_RENDERERS.get((event_type, template_key))
    if renderer is None:
        raise RuntimeError(
            f"No renderer registered for event_type={event_type}, template_key={template_key}."
        )

    output_path = f"marketing_asset_event_{listing_event_id}.png"
    print(f"Selected template: {template_key}")
    renderer(property_id=property_id, agency=agency, output_path=output_path, event_type=event_type)

    try:
        return upload_marketing_asset(
            local_path=output_path,
            listing_event_id=listing_event_id,
            property_id=property_id,
            template_key=template_key,
        )
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)

def load_selected_template(agency_settings_id, event_type):
    response = (
        supabase.table("agency_template_settings")
        .select("template_key")
        .eq("agency_settings_id", agency_settings_id)
        .eq("event_type", event_type)
        .single()
        .execute()
    )
    if not response.data or not response.data.get("template_key"):
        raise RuntimeError(f"No template selected for agency {agency_settings_id} / {event_type}.")
    return response.data["template_key"]


TEMPLATE_RENDERERS = {
    ("NEW_LISTING", "just_listed_01"): render_just_listed_01,
    ("NEW_LISTING", "just_listed_02"): render_just_listed_02,
    ("NEW_LISTING", "just_listed_03"): render_just_listed_03,
    ("PRICE_REDUCED", "just_listed_01"): render_just_listed_01,
    ("PRICE_REDUCED", "just_listed_02"): render_just_listed_02,
    ("PRICE_REDUCED", "just_listed_03"): render_just_listed_03,
    ("RELISTED", "just_listed_01"): render_just_listed_01,
    ("RELISTED", "just_listed_02"): render_just_listed_02,
    ("RELISTED", "just_listed_03"): render_just_listed_03,
}


def render_template(property_id, event_type, output_path=None):
    agency = load_agency()
    agency_id = agency.get("id")
    if not agency_id:
        raise RuntimeError("agency_settings row has no id.")

    template_key = load_selected_template(agency_id, event_type)
    renderer = TEMPLATE_RENDERERS.get((event_type, template_key))

    if renderer is None:
        raise RuntimeError(
            f"No renderer registered for event_type={event_type}, template_key={template_key}."
        )

    print(f"Selected template: {template_key}")
    return renderer(property_id=property_id, agency=agency, output_path=output_path, event_type=event_type)


if __name__=="__main__":
    if len(sys.argv) not in (2, 3, 4):
        print("Usage: python template_renderer.py PROPERTY_ID [EVENT_TYPE] [LISTING_EVENT_ID]")
        raise SystemExit(1)

    try:
        property_id = int(sys.argv[1])
    except ValueError:
        print("PROPERTY_ID must be a number.")
        raise SystemExit(1)

    event_type = sys.argv[2] if len(sys.argv) >= 3 else "NEW_LISTING"

    if len(sys.argv) == 4:
        try:
            listing_event_id = int(sys.argv[3])
        except ValueError:
            print("LISTING_EVENT_ID must be a number.")
            raise SystemExit(1)
        render_and_store_marketing_asset(
            property_id=property_id,
            listing_event_id=listing_event_id,
            event_type=event_type,
        )
    else:
        render_template(property_id=property_id, event_type=event_type)
