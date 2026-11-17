"""Fast real-time develop preview renderer & RGB histogram generator.

Approximates Lightroom Classic's 2012 Process Version sliders on the embedded JPEG preview with NumPy and OpenCV,
so the user can visually inspect Before/After edits, Looks, and Lightroom tweaks inside Virten Studio.

Rendered, in order: exposure, white balance, tone sliders, point curves (one per-channel lookup table), B&W (with the
8-band B&W mix), vibrance and saturation, the 8-band HSL color mixer, split toning, local corrections in linear-gradient
masks (Mask/Gradient, e.g. a Look's light leak) and in AI masks, the post-crop vignette and luminance grain.

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


def _per_channel(rgb_uint8, settings, baseline_temp, baseline_tint):
    """Steps 1-4 (exposure, white balance, tone sliders, point curves): each output channel depends only on the
    same input channel. Returns float32 0..1."""
    img = rgb_uint8.astype(np.float32) / 255.0

    # 1. Exposure2012
    exp = float(settings.get("Exposure2012", 0.0) or 0.0)
    if abs(exp) > 1e-3:
        gain = 2.0 ** (exp * 0.85)
        img = np.power(np.clip(img, 0.0, 1.0), 2.2) * gain
        img = np.power(np.clip(img, 0.0, 1.0), 1.0 / 2.2)

    # 2. White Balance
    temp = settings.get("Temperature")
    tint = settings.get("Tint")
    if isinstance(temp, (int, float)) and temp > 1000:
        mired_shift = (1e6 / baseline_temp) - (1e6 / float(temp))
        t_norm = np.clip(mired_shift / 70.0, -0.35, 0.35)
        img[..., 0] *= (1.0 + t_norm * 0.45)
        img[..., 2] *= (1.0 - t_norm * 0.45)
    if isinstance(tint, (int, float)):
        g_norm = np.clip((float(tint) - baseline_tint) / 100.0, -0.30, 0.30)
        img[..., 1] *= (1.0 - g_norm * 0.35)

    img = np.clip(img, 0.0, 1.0)

    # 3. Tone Sliders
    hi = float(settings.get("Highlights2012", 0.0) or 0.0) / 100.0
    sh = float(settings.get("Shadows2012", 0.0) or 0.0) / 100.0
    wh = float(settings.get("Whites2012", 0.0) or 0.0) / 100.0
    bl = float(settings.get("Blacks2012", 0.0) or 0.0) / 100.0
    con = float(settings.get("Contrast2012", 0.0) or 0.0) / 100.0

    if any(abs(v) > 1e-3 for v in (hi, sh, wh, bl, con)):
        x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        sh_mask = np.power(1.0 - x, 2.2) * x * 3.2
        hi_mask = np.power(x, 2.2) * (1.0 - x) * 3.2
        bl_mask = np.power(1.0 - x, 3.5)
        wh_mask = np.power(x, 3.5)

        y = x + (sh * 0.22 * sh_mask) + (hi * 0.22 * hi_mask) + (wh * 0.14 * wh_mask) + (bl * 0.14 * bl_mask)
        if abs(con) > 1e-3:
            y = 0.5 + (y - 0.5) * (1.0 + con * 0.45) - 0.04 * con * np.sin(2.0 * np.pi * y)
        lut = np.clip(y * 255.0, 0, 255).astype(np.uint8)
        img_u8 = (img * 255.0).astype(np.uint8)
        img = cv2.LUT(img_u8, lut).astype(np.float32) / 255.0

    # 4. Custom Point Tone Curve
    for idx, key in ((None, "ToneCurvePV2012"), (0, "ToneCurvePV2012Red"),
                     (1, "ToneCurvePV2012Green"), (2, "ToneCurvePV2012Blue")):
        pts = settings.get(key)
        if isinstance(pts, list) and len(pts) >= 4 and pts != [0, 0, 255, 255]:
            lut = _build_curve_lut(pts)
            if lut is not None:
                u8 = (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)
                if idx is None:
                    img = cv2.LUT(u8, lut).astype(np.float32) / 255.0
                else:
                    img[..., idx] = cv2.LUT(u8[..., idx], lut).astype(np.float32) / 255.0
    return img


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
            np.clip(1.0 + sat, 0.0, 2.0).astype(np.float32).reshape(1, 256),  # -100 removes colour, +100 doubles it
            (lum * 0.35).astype(np.float32).reshape(1, 256))                  # ±100: up to ±35 % lighter/darker


def _apply_hsl(planes, tables):
    """8-bit HSV round trip (a preview doesn't need more): look up each pixel's hue in the tables."""
    hue_steps, sat_factor, lum_shift = tables
    rgb8 = cv2.merge([cv2.convertScaleAbs(c, alpha=255.0) for c in planes])
    h, s, v = cv2.split(cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV_FULL))
    h2 = np.add(h, cv2.LUT(h, hue_steps), dtype=np.uint8)  # uint8 addition wraps round the colour wheel
    s_f = s.astype(np.float32)
    v2 = v.astype(np.float32) * (1.0 + cv2.LUT(h, lum_shift) * s_f * np.float32(1 / 255))  # greys don't change
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


def render_preview(rgb_uint8, settings, baseline_temp=5400.0, baseline_tint=6.0, ai_masks=None):
    """Applies a Lightroom develop settings dict to an HxWx3 RGB uint8 image.
    ai_masks: compute_ai_masks() of this image, to preview AI-mask corrections (skipped when None).
    Returns a rendered HxWx3 RGB uint8 image."""
    if not settings or rgb_uint8 is None or rgb_uint8.size == 0:
        return rgb_uint8

    # Steps 1-4 as a per-channel lookup table (float, so nothing is rounded before the later steps).
    lut = _per_channel(_RAMP, settings, baseline_temp, baseline_tint).reshape(1, 256, 3)
    img = cv2.LUT(np.ascontiguousarray(rgb_uint8), np.ascontiguousarray(lut, dtype=np.float32))
    # The remaining steps mix channels: work on separate contiguous planes (much faster than strided slices).
    planes = list(cv2.split(img))

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
        # 6. Vibrance & Saturation
        vib = float(settings.get("Vibrance", 0.0) or 0.0) / 100.0
        sat = float(settings.get("Saturation", 0.0) or 0.0) / 100.0
        if abs(vib) > 1e-3 or abs(sat) > 1e-3:
            r, g, b = planes
            lum = _luma709(planes)
            cur_sat = cv2.max(cv2.max(r, g), b) - cv2.min(cv2.min(r, g), b)
            gain = np.clip(cur_sat * 1.5, 0.0, 1.0)
            gain = np.float32(max(0.0, 1.0 + sat)) * (1.0 + np.float32(vib) * (1.0 - gain))
            for c in planes:
                c -= lum
                c *= gain
                c += lum
                np.clip(c, 0.0, 1.0, out=c)

        # 6b. HSL / Color Mixer
        tables = _hsl_tables(settings)
        if tables is not None:
            planes = _apply_hsl(planes, tables)

        # 7. Split Toning (a blend toward the tint colour stays within 0..1, so no clipping needed)
        sh_sat = float(settings.get("SplitToningShadowSaturation", 0.0) or 0.0) / 100.0
        hi_sat = float(settings.get("SplitToningHighlightSaturation", 0.0) or 0.0) / 100.0
        if sh_sat > 0.01 or hi_sat > 0.01:
            lum = _luma709(planes)
            tmp = np.empty_like(lum)
            for amount, hue_key, shadows in ((sh_sat, "SplitToningShadowHue", True),
                                             (hi_sat, "SplitToningHighlightHue", False)):
                if amount <= 0.01:
                    continue
                tint_rgb = _hue_to_rgb(float(settings.get(hue_key, 0.0) or 0.0))
                w = (1.0 - lum * 1.6) if shadows else ((lum - 0.4) * 1.6)
                np.clip(w, 0.0, 1.0, out=w)
                w *= np.float32(amount * 0.22)
                for i, c in enumerate(planes):  # c += w * (tint - c)
                    np.subtract(tint_rgb[i], c, out=tmp)
                    tmp *= w
                    c += tmp

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
