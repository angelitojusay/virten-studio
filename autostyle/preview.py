"""Fast real-time develop preview renderer & RGB histogram generator.

Approximates Lightroom Classic's 2012 Process Version sliders on the embedded JPEG preview with NumPy and OpenCV,
so the user can visually inspect Before/After edits, Looks, and Lightroom tweaks inside Virten Studio.

Rendered, in order: exposure and white balance (linear light, relative to the photo's as-shot white balance), the
tone sliders, parametric and point curves (computed on luminance, with Lightroom-like chroma coupling), clarity and
texture, B&W (with the 8-band B&W mix), skin-protected vibrance and soft-knee saturation, the 8-band HSL color mixer,
split toning / color grading, local corrections in linear-gradient masks (Mask/Gradient, e.g. a Look's light leak) and in
AI masks, the post-crop vignette and luminance grain. Chroma that would leave the sRGB gamut is compressed softly, so
saturated and bright warm tones don't clip into neon.

The strengths are the CAL constants, fitted against Lightroom Classic's own rendered previews of real edited photos
(dev-tools/calibrate_preview.py). The base image is the camera's embedded JPEG: close to Lightroom's default rendering
(measured: ~5 % more chroma), and much faster than demosaicing the RAW.

AI masks (subject, background, sky, skin) are *simulated* for the preview by compute_ai_masks() (people segmentation
plus a sky heuristic); Lightroom computes its own, more precise selections when the edits are applied.

Speed: exposure, white balance, the tone sliders and the tone curves change each colour channel independently, so
they're evaluated once for the 256 possible input values and applied to the photo as a lookup table. The HSL mixer is
an 8-bit HSV round trip with 256-entry per-hue tables, gradients are a separable weight ramp and grain noise is cached
per image size. About 15-55 ms for a 960 px preview, depending on the Look."""
from functools import lru_cache

import cv2
import numpy as np

_RAMP = np.repeat(np.arange(256, dtype=np.uint8).reshape(256, 1, 1), 3, axis=2)  # every input value, per channel


def _build_curve_lut(points):
    if not points or len(points) < 4:
        return None
    xs = np.array(points[0::2], dtype=np.float32)
    ys = np.array(points[1::2], dtype=np.float32)
    lut = np.interp(np.arange(256, dtype=np.float32), xs, ys)
    return np.clip(lut, 0, 255).astype(np.uint8)


# Calibration constants. Measured against Lightroom Classic's own rendered previews of 274 real photos from six shoots
# (dev-tools/calibrate_preview.py; one shoot held out): exposure, white balance, tint, tone and contrast strengths
# were fitted; saturation, HSL and vibrance follow Lightroom's documented range (-100 removes colour, +100 roughly
# doubles it); the couplings follow its behaviour (tone changes carry ~60 % into chroma; Contrast adds a little
# saturation). Held-out shoot: median colour difference dE 7.8 -> 5.1, saturation 0.98x and skin 0.99x Lightroom's.
CAL = {
    "exp_k": 0.663,      # Exposure: stops per Exposure unit, in linear light (Lightroom rolls highlights off)
    "wb_k": 0.682,       # White balance: log2 gain on red / blue per 100 mired from the as-shot white balance
    "tint_k": 0.278,     # Tint: log2 gain on green per 100 Tint units
    "tone_k": 1.184,     # Highlights / Shadows / Whites / Blacks amplitude
    "con_k": 0.351,      # Contrast: midtone slope change per 100
    "con_sat": 0.3,      # Contrast also lifts saturation (as in Lightroom): chroma gain per +100 Contrast
    "chroma_c": 0.6,     # how much a tone change carries into chroma (0 = keep chroma, 1 = scale chroma like RGB)
    "curve_c": 0.9,      # the same for the point / parametric curves (Lightroom applies those closer to RGB)
    "param_k": 0.18,     # parametric curve region amplitude at +-100
    "vib_k": 1.0,        # Vibrance: chroma gain at +100 on a fully muted colour (less on saturated colours and skin)
    "vib_skin": 0.6,     # how much Vibrance holds back on skin hues (10-45 degrees)
    "sat_k": 1.0,        # Saturation: chroma gain at +100 (rolls off at the gamut edge)
    "knee": 0.85,        # soft-knee start: share of the sRGB gamut where added chroma starts to compress
    "hsl_sat_k": 1.0,    # HSL saturation: chroma factor change at +-100 (-100 removes the band's colour)
    "hsl_lum_k": 0.35,   # HSL luminance: up to +-35 % lighter / darker at +-100
    "split_k": 0.22,     # split toning / color grading tint strength at saturation 100
}
_GAMMA = 2.2

# As-shot white balance from the camera's own WB multipliers (r/g, b/g), per camera model, for photos whose catalog
# doesn't hold Lightroom's "As Shot" value (edited before Lightroom computed it): mired = a + b ln(r/g) + c ln(b/g),
# Tint likewise. Fitted on Lightroom's As Shot values of 389 photos (median error 10 mired / 4 Tint on held-out shoots).
AS_SHOT_MODELS = {"ILCE-1": ((354.363, -231.309, 51.571), (-158.901, 138.342, 113.994))}


def estimate_as_shot(wb_r, wb_b, camera):
    """(Temperature, Tint) Lightroom would call "As Shot" for these camera multipliers, or None (unknown camera)."""
    model = AS_SHOT_MODELS.get(camera or "")
    try:
        lr, lb = float(np.log(float(wb_r))), float(np.log(float(wb_b)))
    except (TypeError, ValueError):
        return None
    if not model or not np.isfinite(lr) or not np.isfinite(lb):
        return None
    (a, b, c), (d, e, f) = model
    mired = a + b * lr + c * lb
    if not 80.0 < mired < 600.0:
        return None
    return round(1e6 / mired), round(d + e * lr + f * lb)


def _shoulder(x, gain):
    """Soft highlight roll-off for linear values a gain pushes past white (Lightroom doesn't hard-clip exposure or
    white balance). Fades in as the gain rises above 1, so an unchanged channel stays exactly as it was."""
    w = float(np.clip((gain - 1.0) / 0.5, 0.0, 1.0))
    if w <= 0.0:
        return np.minimum(x, 1.0)
    soft = np.where(x < 0.8, x, 0.8 + 0.2 * np.tanh((x - 0.8) / 0.2))
    return (1.0 - w) * np.minimum(x, 1.0) + w * soft


def _wb_exposure_gains(settings, as_shot_temp, as_shot_tint):
    """Linear-light (R, G, B) gains for Exposure2012 and Temperature / Tint relative to the as-shot white balance
    (the embedded preview is already balanced as shot). Grey keeps its luminance; unknown as-shot = no WB change."""
    gr = gg = gb = 1.0
    temp, tint = settings.get("Temperature"), settings.get("Tint")
    if isinstance(temp, (int, float)) and temp > 1000 and as_shot_temp:
        dm = 1e6 / float(temp) - 1e6 / float(as_shot_temp)  # + = a cooler setting than as shot (more blue)
        gr *= 2.0 ** (-CAL["wb_k"] * dm / 100.0)
        gb *= 2.0 ** (CAL["wb_k"] * dm / 100.0)
    if isinstance(tint, (int, float)) and as_shot_tint is not None:
        gg *= 2.0 ** (-CAL["tint_k"] * (float(tint) - float(as_shot_tint)) / 100.0)  # + tint = magenta = less green
    norm = 0.2126 * gr + 0.7152 * gg + 0.0722 * gb
    e = 2.0 ** (float(settings.get("Exposure2012", 0.0) or 0.0) * CAL["exp_k"])
    return e * gr / norm, e * gg / norm, e * gb / norm


def _per_channel_lut(settings, as_shot_temp, as_shot_tint):
    """Exposure and white balance as a (1, 256, 3) float lookup table: each channel is independent here."""
    x = np.arange(256, dtype=np.float32) / 255.0
    lin = x ** _GAMMA
    gains = _wb_exposure_gains(settings, as_shot_temp, as_shot_tint)
    chans = [np.clip(_shoulder(lin * np.float32(g), g), 0.0, 1.0) ** (1.0 / _GAMMA) for g in gains]
    return np.stack(chans, axis=-1).astype(np.float32).reshape(1, 256, 3)


def _bump(x, centre, width):
    return np.clip(1.0 - np.abs(x - centre) / width, 0.0, 1.0) ** 2 * (3 - 2 * np.clip(1.0 - np.abs(x - centre) / width, 0.0, 1.0))


def _tone_curves(settings):
    """(sliders curve, point+parametric curve) as 1024-step tables on 0..1 luminance, or None when untouched."""
    x = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
    hi = float(settings.get("Highlights2012", 0.0) or 0.0) / 100.0
    sh = float(settings.get("Shadows2012", 0.0) or 0.0) / 100.0
    wh = float(settings.get("Whites2012", 0.0) or 0.0) / 100.0
    bl = float(settings.get("Blacks2012", 0.0) or 0.0) / 100.0
    con = float(settings.get("Contrast2012", 0.0) or 0.0) / 100.0
    sliders = None
    if any(abs(v) > 1e-3 for v in (hi, sh, wh, bl, con)):
        k = CAL["tone_k"]
        y = (x + k * (sh * 0.22 * (1.0 - x) ** 2.2 * x * 3.2 + hi * 0.22 * x ** 2.2 * (1.0 - x) * 3.2
                      + wh * 0.14 * x ** 3.5 + bl * 0.14 * (1.0 - x) ** 3.5))
        if abs(con) > 1e-3:
            y = 0.5 + (y - 0.5) * (1.0 + con * CAL["con_k"]) - 0.04 * con * np.sin(2.0 * np.pi * y)
        sliders = np.clip(y, 0.0, 1.0)
    # Parametric curve: four regions split at ShadowSplit / MidtoneSplit / HighlightSplit (Lightroom's defaults 25/50/75)
    regions = [float(settings.get(k, 0.0) or 0.0) / 100.0 for k in
               ("ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights")]
    curve = None
    if any(abs(v) > 1e-3 for v in regions):
        s1 = float(settings.get("ParametricShadowSplit", 25) or 25) / 100.0
        s2 = float(settings.get("ParametricMidtoneSplit", 50) or 50) / 100.0
        s3 = float(settings.get("ParametricHighlightSplit", 75) or 75) / 100.0
        centres = (s1 / 2, (s1 + s2) / 2, (s2 + s3) / 2, (s3 + 1) / 2)
        widths = (s1, (s2 - s1), (s3 - s2), (1 - s3))
        y = x.copy()
        for amt, c, w in zip(regions, centres, widths):
            y = y + CAL["param_k"] * amt * _bump(x, c, max(w * 1.6, 0.08))
        curve = np.clip(y, 0.0, 1.0)
    pts = settings.get("ToneCurvePV2012")
    if isinstance(pts, list) and len(pts) >= 4 and pts != [0, 0, 255, 255]:
        lut = _build_curve_lut(pts).astype(np.float32) / 255.0
        base = curve if curve is not None else x
        curve = np.interp(base, np.linspace(0, 1, 256, dtype=np.float32), lut).astype(np.float32)
    return sliders, curve


def _gamut_use(y, d):
    """Per pixel: the share of the sRGB gamut used along the pixel's chroma direction (1 = a channel at 0 or 1)."""
    dmax = np.maximum(np.maximum(d[0], d[1]), d[2])  # the channel furthest above the luminance...
    dmin = np.minimum(np.minimum(d[0], d[1]), d[2])  # ...and the one furthest below it
    return np.maximum(dmax / np.maximum(1.0 - y, np.float32(1e-6)), -dmin / np.maximum(y, np.float32(1e-6)))


def _soft_chroma(y, d, u_before, u=None):
    """Scales chroma back where it was pushed past the soft knee (or past what the pixel already had), with a tanh
    roll-off, so added saturation approaches the gamut boundary smoothly instead of clipping. Hue and luminance stay."""
    if u is None:
        u = _gamut_use(y, d)
    ceiling = np.float32(0.985)  # added chroma levels off just inside the gamut: no channel is driven to 0 or 255
    limit = np.minimum(np.maximum(u_before, np.float32(CAL["knee"])), ceiling)
    over = u > limit
    if not over.any():
        return d
    room = np.maximum(ceiling - limit[over], 1e-3)
    s = np.ones_like(u)
    uo = u[over]
    s[over] = (limit[over] + room * np.tanh((uo - limit[over]) / room)) / np.maximum(uo, 1e-6)
    return [dc * s for dc in d]


_STEPS = 4096
_XS = np.linspace(0.0, 1.0, _STEPS, dtype=np.float32)


def _index(a):
    """4096-step table index of 0..1 values."""
    return np.clip(a * np.float32(_STEPS - 1) + np.float32(0.5), 0, _STEPS - 1).astype(np.int32)


def _apply_tone(planes, settings):
    """Tone sliders and curves on luminance; chroma follows by (Y'/Y) ** coupling (plus Contrast's saturation lift).
    Both depend only on the input luminance, so they're 4096-step tables. Channel point curves per channel."""
    sliders, curve = _tone_curves(settings)
    if sliders is not None or curve is not None:
        grid = np.linspace(0.0, 1.0, 1024, dtype=np.float32)
        y1t = np.interp(_XS, grid, sliders).astype(np.float32) if sliders is not None else _XS
        y2t = np.interp(y1t, grid, curve).astype(np.float32) if curve is not None else y1t
        eps = np.float32(0.02)
        kt = (((y1t + eps) / (_XS + eps)) ** np.float32(CAL["chroma_c"])
              * ((y2t + eps) / (y1t + eps)) ** np.float32(CAL["curve_c"])).astype(np.float32)
        con = float(settings.get("Contrast2012", 0.0) or 0.0) / 100.0
        if abs(con) > 1e-3:
            kt *= np.float32(max(0.0, 1.0 + con * CAL["con_sat"]))
        y = np.clip(_luma709(planes), 0.0, 1.0)
        d = [c - y for c in planes]
        u0 = _gamut_use(y, d)
        idx = _index(y)
        y2 = y2t[idx]
        k = kt[idx]
        d = _soft_chroma(y2, [dc * k for dc in d], u0)
        planes = [np.clip(y2 + dc, 0.0, 1.0) for dc in d]
        if curve is not None:  # like Lightroom's per-channel point curve: no channel leaves the curve's output range
            top, bottom = float(curve[-1]), float(curve[0])
            if top < 0.999 or bottom > 0.001:
                knee = max(top - 0.03, bottom)
                room = max(top - knee, 1e-3)
                ceil = np.where(_XS > knee, knee + room * np.tanh((_XS - knee) / room), _XS)
                ceil = np.maximum(ceil, np.float32(bottom)).astype(np.float32)
                planes = [ceil[_index(c)] for c in planes]
    for idx_c, key in ((0, "ToneCurvePV2012Red"), (1, "ToneCurvePV2012Green"), (2, "ToneCurvePV2012Blue")):
        pts = settings.get(key)
        if isinstance(pts, list) and len(pts) >= 4 and pts != [0, 0, 255, 255]:
            lut = _build_curve_lut(pts).astype(np.float32) / 255.0
            planes[idx_c] = np.interp(planes[idx_c], np.linspace(0, 1, 256, dtype=np.float32), lut).astype(np.float32)
    return planes


def _hue_deg(planes):
    r, g, b = planes
    return cv2.phase(2.0 * r - g - b, np.float32(np.sqrt(3.0)) * (g - b), angleInDegrees=True)


def _apply_vibrance_saturation(planes, settings):
    """Vibrance boosts muted colours most and holds back on skin hues (10-45 degrees); Saturation is an even chroma gain.
    Both end in the soft knee, so already-saturated colours roll off instead of clipping."""
    vib = float(settings.get("Vibrance", 0.0) or 0.0) / 100.0
    sat = float(settings.get("Saturation", 0.0) or 0.0) / 100.0
    if abs(vib) < 1e-3 and abs(sat) < 1e-3:
        return planes
    y = np.clip(_luma709(planes), 0.0, 1.0)
    d = [c - y for c in planes]
    u0 = _gamut_use(y, d)
    factor = np.float32(max(0.0, 1.0 + sat * CAL["sat_k"]))
    if abs(vib) > 1e-3:
        mx = np.maximum(np.maximum(planes[0], planes[1]), planes[2])
        mn = np.minimum(np.minimum(planes[0], planes[1]), planes[2])
        hsv_sat = (mx - mn) / np.maximum(mx, 1e-3)
        muted = np.clip(1.0 - hsv_sat, 0.0, 1.0)
        h = _hue_deg(planes)
        skin = np.clip(np.minimum((h - 5.0) / 10.0, (50.0 - h) / 10.0), 0.0, 1.0)  # 1 within 15-40 deg, ramps to 5 / 50
        w = muted * (1.0 - np.float32(CAL["vib_skin"]) * skin)
        factor = factor * np.maximum(0.0, 1.0 + np.float32(vib * CAL["vib_k"]) * w)
    d = [dc * factor for dc in d]
    d = _soft_chroma(y, d, u0, u0 * factor)  # a chroma scale scales the gamut share alike
    return [np.clip(y + dc, 0.0, 1.0) for dc in d]


def _apply_toning(planes, settings):
    """Split toning and color grading (shadows / midtones / highlights / global tints): a blend toward the tint colour,
    weighted by tone; stays inside 0..1."""
    lum = _luma709(planes)
    zones = []
    for hue_k, sat_k, zone in (("SplitToningShadowHue", "SplitToningShadowSaturation", "shadows"),
                               ("SplitToningHighlightHue", "SplitToningHighlightSaturation", "highlights"),
                               ("ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "midtones"),
                               ("ColorGradeGlobalHue", "ColorGradeGlobalSat", "global")):
        amount = float(settings.get(sat_k, 0.0) or 0.0) / 100.0
        if amount > 0.01:
            zones.append((amount, float(settings.get(hue_k, 0.0) or 0.0), zone))
    if not zones:
        return planes
    tmp = np.empty_like(lum)
    for amount, hue, zone in zones:
        tint_rgb = _hue_to_rgb(hue)
        if zone == "shadows":
            w = 1.0 - lum * 1.6
        elif zone == "highlights":
            w = (lum - 0.4) * 1.6
        elif zone == "midtones":
            w = 1.0 - np.abs(lum - 0.5) * 2.2
        else:
            w = np.ones_like(lum)
        w = np.clip(w, 0.0, 1.0) * np.float32(amount * CAL["split_k"])
        for i, c in enumerate(planes):  # c += w * (tint - c)
            np.subtract(tint_rgb[i], c, out=tmp)
            tmp *= w
            c += tmp
    return planes


@lru_cache(maxsize=8)
def _vignette_falloff(h, w):
    """0 in the centre rising to 1 in the corners (float32 HxW), cached per preview size."""
    yy, xx = np.ogrid[:h, :w]
    cy, cx = h / 2.0, w / 2.0
    r2 = ((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2
    return np.clip((r2 - 0.35) / 1.1, 0.0, 1.0).astype(np.float32)


# Lightroom's HSL bands and their hue centres in degrees (Purple/Magenta sit closer together than the others).
HSL_BANDS = (("Red", 0), ("Orange", 30), ("Yellow", 60), ("Green", 120), ("Aqua", 180), ("Blue", 240),
             ("Purple", 270), ("Magenta", 300))


def _hsl_tables(settings):
    """Per-hue lookup tables for the 8-band mixer over the 256 hue steps of 8-bit HSV (0..255 = 0..360°), or None when
    the mixer is untouched. Between two band centres the effect blends linearly, like Lightroom's overlapping bands.
    Returns (hue shift in hue steps as uint8, wrapping; saturation factor; lightness shift), each shaped (1, 256)."""
    vals = [[float(settings.get(f"{kind}Adjustment{band}", 0) or 0) / 100.0 for band, _ in HSL_BANDS]
            for kind in ("Hue", "Saturation", "Luminance")]
    if not any(abs(v) > 1e-3 for row in vals for v in row):
        return None
    centres = np.array([c for _, c in HSL_BANDS] + [360], np.float32)
    hues = np.arange(256, dtype=np.float32) * (360.0 / 256.0)
    hue, sat, lum = (np.interp(hues, centres, np.array(row + [row[0]], np.float32)) for row in vals)
    hue_steps = np.round(hue * 30.0 * (256.0 / 360.0)).astype(np.int64) % 256  # ±100 moves the hue about ±30°
    return (hue_steps.astype(np.uint8).reshape(1, 256),
            np.clip(1.0 + sat * CAL["hsl_sat_k"], 0.0, 2.5).astype(np.float32).reshape(1, 256),  # -100: no colour
            (lum * CAL["hsl_lum_k"]).astype(np.float32).reshape(1, 256))


def _apply_hsl(planes, tables):
    """8-bit HSV round trip (a preview doesn't need more): look up each pixel's hue in the tables."""
    hue_steps, sat_factor, lum_shift = tables
    rgb8 = cv2.merge([cv2.convertScaleAbs(c, alpha=255.0) for c in planes])
    h, s, v = cv2.split(cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV_FULL))
    h2 = np.add(h, cv2.LUT(h, hue_steps), dtype=np.uint8)  # uint8 addition wraps round the colour wheel
    s_f = s.astype(np.float32)
    v_f = v.astype(np.float32)
    v2 = v_f * (1.0 + cv2.LUT(h, lum_shift) * s_f * np.float32(1 / 255))  # greys don't change
    # Brightened colours approach white softly instead of clipping (unchanged pixels stay exactly as they were).
    limit = np.maximum(v_f, np.float32(235.0))
    room = np.maximum(np.float32(254.0) - limit, np.float32(1.0))
    v2 = np.where(v2 > limit, limit + room * np.tanh((v2 - limit) / room), v2)
    s2 = s_f * cv2.LUT(h, sat_factor)
    hsv = cv2.merge([h2, cv2.convertScaleAbs(s2), cv2.convertScaleAbs(v2)])
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB_FULL)
    return [c.astype(np.float32) * np.float32(1 / 255) for c in cv2.split(rgb)]


def _gray_mix_table(settings):
    """Per-hue brightness factor for the B&W mix (GrayMixer{Red..Magenta}, -100..100) over the 256 hue steps, or None.
    Weighted by saturation when applied, so neutral greys keep their tone."""
    vals = [float(settings.get(f"GrayMixer{band}", 0) or 0) / 100.0 for band, _ in HSL_BANDS]
    if not any(abs(v) > 1e-3 for v in vals):
        return None
    centres = np.array([c for _, c in HSL_BANDS] + [360], np.float32)
    hues = np.arange(256, dtype=np.float32) * (360.0 / 256.0)
    return (np.interp(hues, centres, np.array(vals + [vals[0]], np.float32)) * 0.6).astype(np.float32).reshape(1, 256)


# ---------------------------------------------------------------- simulated AI masks

AI_MASK_KINDS = ("subject", "background", "sky", "skin")


def compute_ai_masks(rgb_uint8):
    """Soft (feathered) 0..1 float32 masks the size of the image, standing in for Lightroom's AI selections in the
    preview: "subject" (people incl. hair and clothes), "background" (everything else), "skin" (face and body skin)
    and "sky" (smooth, bright or blue background regions connected to the top edge). ~30-60 ms at 960 px."""
    from . import vision
    h, w = rgb_uint8.shape[:2]
    seg = vision.segment_people(rgb_uint8)
    people = (seg > 0).astype(np.float32)
    skin = ((seg == 2) | (seg == 3)).astype(np.float32)

    # Sky: on a small copy, background pixels that are smooth and either bright or blue/cyan, connected to the top.
    s = 240.0 / max(h, w)
    sw, sh = max(8, round(w * s)), max(8, round(h * s))
    small = cv2.resize(rgb_uint8, (sw, sh), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV_FULL)
    hue = hsv[..., 0].astype(np.float32) * (360.0 / 256.0)
    sat = hsv[..., 1].astype(np.float32) / 255.0
    val = hsv[..., 2].astype(np.float32) / 255.0
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    texture = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (0, 0), 1.5)
    bluish = (hue > 170) & (hue < 260) & (sat > 0.12) & (val > 0.3)
    bright = (val > 0.62) & (sat < 0.35)
    not_people = cv2.resize(people, (sw, sh), interpolation=cv2.INTER_AREA) < 0.3
    rows = (np.arange(sh)[:, None] < 0.75 * sh)
    cand = (texture < 0.035) & (bluish | bright) & not_people & rows
    sky = np.cumprod(cand, axis=0).astype(np.float32)  # columns of sky that start at the top edge
    sky = cv2.resize(sky, (w, h), interpolation=cv2.INTER_LINEAR)

    sigma = max(1.0, 0.008 * max(h, w))
    feather = lambda m: cv2.GaussianBlur(m, (0, 0), sigma)  # noqa: E731
    subject = feather(people)
    return {"subject": subject, "background": 1.0 - subject, "skin": feather(skin),
            "sky": np.clip(feather(sky), 0.0, 1.0)}


def ai_mask_kind(group):
    """'subject' / 'background' / 'sky' / 'skin' for a Mask/Image correction group (None for teeth etc.)."""
    from . import tools
    kind = tools.mask_kind(group)
    return kind if kind in AI_MASK_KINDS else None


def active_ai_kinds(settings):
    """AI mask kinds used by active correction groups in these settings."""
    out = []
    for g in settings.get("MaskGroupBasedCorrections") or []:
        if isinstance(g, dict) and g.get("CorrectionActive") is not False:
            k = ai_mask_kind(g)
            if k and k not in out:
                out.append(k)
    return out


def _gradient_weight(h, w, zero, full):
    """0 at the 'zero' point rising to 1 at the 'full' point (image fractions), constant across the gradient."""
    zx, zy = float(zero[0]), float(zero[1])
    dx, dy = float(full[0]) - zx, float(full[1]) - zy
    n2 = dx * dx + dy * dy
    if n2 < 1e-9:
        return None
    xs = ((np.arange(w, dtype=np.float32) + 0.5) / w - zx) * (dx / n2)
    ys = ((np.arange(h, dtype=np.float32) + 0.5) / h - zy) * (dy / n2)
    return np.clip(ys[:, None] + xs[None, :], 0.0, 1.0)


def _correction_weight(g, shape, ai_masks):
    """The 0..1 weight map of one correction group: a linear gradient, or a (simulated) AI mask. None if unknown."""
    masks = [m for m in g.get("CorrectionMasks") or [] if isinstance(m, dict)]
    grads = [m for m in masks if m.get("What") == "Mask/Gradient"]
    if grads:
        m = grads[0]
        try:
            wgt = _gradient_weight(*shape, (m["ZeroX"], m["ZeroY"]), (m["FullX"], m["FullY"]))
        except (KeyError, TypeError, ValueError):
            return None
    elif any(m.get("What") == "Mask/Image" for m in masks) and ai_masks:
        kind = ai_mask_kind(g)
        if not kind or kind not in ai_masks:
            return None  # e.g. teeth: no stand-in selection
        wgt = ai_masks[kind]
        if wgt.shape != shape:
            wgt = cv2.resize(wgt, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
        m = next(m for m in masks if m.get("What") == "Mask/Image")
    else:
        return None
    if wgt is None:
        return None
    if m.get("MaskInverted"):
        wgt = 1.0 - wgt
    return wgt * np.float32(float(g.get("CorrectionAmount", 1.0) or 0.0))


def _apply_local_corrections(planes, settings, ai_masks=None):
    """Local exposure, contrast, highlights, shadows, temperature, tint and saturation inside each gradient or AI mask
    (local sliders are stored -1..1; exposure as EV / 4)."""
    for g in settings.get("MaskGroupBasedCorrections") or []:
        if not isinstance(g, dict) or g.get("CorrectionActive") is False:
            continue
        wgt = _correction_weight(g, planes[0].shape, ai_masks)
        if wgt is None:
            continue
        loc = lambda k: float(g.get(k, 0.0) or 0.0)  # noqa: E731
        r, gg, b = planes = [c.copy() for c in planes]  # in place from here on (callers may share arrays)
        ev = loc("LocalExposure2012") * 4.0
        if abs(ev) > 1e-3:
            gain = np.exp2(wgt * np.float32(ev * 0.85))
            for c in planes:
                c *= gain
        temp, tint = loc("LocalTemperature"), loc("LocalTint")
        if abs(temp) > 1e-3:
            f = wgt * np.float32(temp * 0.25)
            r *= 1.0 + f
            b *= 1.0 - f
        if abs(tint) > 1e-3:  # positive tint = magenta = less green
            gg *= 1.0 - wgt * np.float32(tint * 0.2)
        con = loc("LocalContrast2012")
        if abs(con) > 1e-3:
            k = 1.0 + wgt * np.float32(con * 0.5)
            for c in planes:
                c -= 0.5
                c *= k
                c += 0.5
        hi, sh = loc("LocalHighlights2012"), loc("LocalShadows2012")
        if abs(hi) > 1e-3 or abs(sh) > 1e-3:
            lum = _luma709(planes)
            if abs(hi) > 1e-3:  # scales the bright tones (negative = recover highlights)
                k = 1.0 + wgt * np.clip((lum - 0.45) * 1.8, 0.0, 1.0) * np.float32(hi * 0.35)
                for c in planes:
                    c *= k
            if abs(sh) > 1e-3:  # lifts (or deepens) the dark tones
                add = wgt * np.clip((0.55 - lum) * 1.8, 0.0, 1.0) * np.float32(sh * 0.2)
                for c in planes:
                    c += add
        sat = loc("LocalSaturation")
        if abs(sat) > 1e-3:
            lum = _luma709(planes)
            k = 1.0 + wgt * np.float32(sat)
            for c in planes:
                c -= lum
                c *= k
                c += lum
        for c in planes:
            np.clip(c, 0.0, 1.0, out=c)
    return planes


@lru_cache(maxsize=4)
def _grain_noise(h, w, size):
    """Unit-variance film-grain noise for an image size (fixed seed, so it doesn't flicker while you adjust)."""
    rng = np.random.default_rng(1234)
    n = rng.standard_normal((h, w), dtype=np.float32)
    sigma = 0.4 + float(size) / 40.0  # Lightroom's Size 25 is fine grain; larger sizes clump more
    n = cv2.GaussianBlur(n, (0, 0), sigma)
    return n / max(float(n.std()), 1e-6)


def _luma709(planes):
    r, g, b = planes
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def render_preview(rgb_uint8, settings, baseline_temp=None, baseline_tint=None, ai_masks=None):
    """Applies a Lightroom develop settings dict to an HxWx3 sRGB uint8 image (the camera's embedded preview).
    baseline_temp / baseline_tint: the photo's as-shot white balance (Lightroom's "As Shot" Temperature / Tint), which
    the embedded preview already has; Temperature / Tint are shown relative to it. None: the white balance is shown
    as shot (unknown as-shot white balance, or settings that keep it).
    ai_masks: compute_ai_masks() of this image, to preview AI-mask corrections (skipped when None).
    Returns a rendered HxWx3 sRGB uint8 image."""
    if not settings or rgb_uint8 is None or rgb_uint8.size == 0:
        return rgb_uint8
    if settings.get("WhiteBalance") == "As Shot":
        baseline_temp, baseline_tint = settings.get("Temperature"), settings.get("Tint")

    # Exposure and white balance as a per-channel lookup table (float, so nothing is rounded before later steps).
    lut = _per_channel_lut(settings, baseline_temp, baseline_tint)
    img = cv2.LUT(np.ascontiguousarray(rgb_uint8), np.ascontiguousarray(lut, dtype=np.float32))
    # The remaining steps mix channels: work on separate contiguous planes (much faster than strided slices).
    planes = list(cv2.split(img))
    planes = _apply_tone(planes, settings)

    # 4b. Clarity (midtone local contrast, large radius) and Texture (fine detail, small radius): unsharp masks on
    # the luminance, added to every channel so colours don't shift. A simulation of Lightroom's local contrast.
    for key, radius, gain, midtones in (("Clarity2012", 60.0, 0.9, True), ("Texture", 240.0, 0.6, False)):
        amount = float(settings.get(key, 0.0) or 0.0) / 100.0
        if abs(amount) > 1e-3:
            lum = _luma709(planes)
            detail = lum - cv2.GaussianBlur(lum, (0, 0), max(1.0, max(lum.shape) / radius))
            if midtones:
                detail *= 1.0 - (2.0 * lum - 1.0) ** 2
            detail *= np.float32(amount * gain)
            for c in planes:
                c += detail
                np.clip(c, 0.0, 1.0, out=c)

    # 5. Grayscale / B&W Conversion (the B&W mix brightens/darkens colours by hue before they turn grey)
    if settings.get("ConvertToGrayscale"):
        lum = 0.299 * planes[0] + 0.587 * planes[1] + 0.114 * planes[2]
        mix = _gray_mix_table(settings)
        if mix is not None:
            rgb8 = cv2.merge([cv2.convertScaleAbs(c, alpha=255.0) for c in planes])
            h, s, _ = cv2.split(cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV_FULL))
            lum = lum * (1.0 + cv2.LUT(h, mix) * s.astype(np.float32) * np.float32(1 / 255))
        planes = [lum, lum.copy(), lum.copy()]  # separate arrays: later steps work in place
    else:
        # 6. Vibrance (skin-protected, muted-weighted) & Saturation (soft knee)
        planes = _apply_vibrance_saturation(planes, settings)

        # 6b. HSL / Color Mixer
        tables = _hsl_tables(settings)
        if tables is not None:
            planes = _apply_hsl(planes, tables)

        # 7. Split toning / color grading
        planes = _apply_toning(planes, settings)

    # 7b. Local corrections: linear gradients (a Look's light leak) and simulated AI masks (subject, sky...)
    if settings.get("MaskGroupBasedCorrections"):
        planes = _apply_local_corrections(planes, settings, ai_masks)

    # 8. Post-Crop Vignette (the final conversion clips)
    vig = float(settings.get("PostCropVignetteAmount", 0.0) or 0.0) / 100.0
    if abs(vig) > 0.02:
        mask = 1.0 + np.float32(vig * 0.45) * _vignette_falloff(*planes[0].shape)
        for c in planes:
            c *= mask

    # 9. Grain (monochrome, on all channels alike)
    grain = float(settings.get("GrainAmount", 0.0) or 0.0) / 100.0
    if grain > 0.01:
        h, w = planes[0].shape
        noise = _grain_noise(h, w, int(settings.get("GrainSize", 25) or 25)) * np.float32(grain * 0.07)
        for c in planes:
            c += noise

    return cv2.merge([cv2.convertScaleAbs(np.maximum(c, 0.0), alpha=255.0) for c in planes])


def _hue_to_rgb(hue_deg):
    hsv = np.uint8([[[int((hue_deg % 360) / 2), 220, 220]]])
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0, 0].astype(np.float32) / 255.0
    return rgb


def compute_histogram(rgb_uint8, bins=64):
    """Returns (r_hist, g_hist, b_hist, lum_hist) normalized to 0..1 for the UI histogram widget."""
    if rgb_uint8 is None or rgb_uint8.size == 0:
        z = np.zeros(bins, dtype=np.float32)
        return z, z, z, z
    out = []
    for c in range(3):
        h = cv2.calcHist([rgb_uint8], [c], None, [bins], [0, 256]).ravel()
        out.append(h / max(float(h.max()), 1.0))
    gray = cv2.cvtColor(rgb_uint8, cv2.COLOR_RGB2GRAY)
    lh = cv2.calcHist([gray], [0], None, [bins], [0, 256]).ravel()
    out.append(lh / max(float(lh.max()), 1.0))
    return tuple(out)
