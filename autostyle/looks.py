"""Looks: stylistic layers (cinematic, film, B&W…) applied on top of a personal profile's per-photo edits.

A look has two parts:
  set    - absolute values (tone curve, color grading, HSL, calibration, grain, vignette, B&W mix)
  offset - shifts added to the profile's per-photo values (exposure, contrast, temperature…)
  masks  - optional linear gradients (e.g. a light leak), added as Lightroom masks: zero/full points as image
           fractions, local slider values -1..1 (scaled by strength)
Strength 0-1 blends from the profile's own result (0) to the full look (1)."""
import json
import os
import re
import xml.etree.ElementTree as ET

from . import tools
from .paths import data_dir, resource_dir

BUILTIN_DIR = os.path.join(resource_dir(), "looks")
IDENTITY_CURVE = [0, 0, 255, 255]
CURVE_KEYS = ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")
DEFAULTS = {"ColorGradeBlending": 50, "GrainSize": 25, "GrainFrequency": 50, "PostCropVignetteMidpoint": 50,
            "PostCropVignetteFeather": 50, "PostCropVignetteStyle": 1, "ParametricShadowSplit": 25,
            "ParametricMidtoneSplit": 50, "ParametricHighlightSplit": 75, "Sharpness": 40, "SharpenRadius": 1,
            "SharpenDetail": 25}
RANGES = {"Exposure2012": (-5, 5), "Temperature": (2000, 50000), "Tint": (-150, 150)}
# Keys a preset sets relative to a neutral photo; applied as shifts so the per-photo corrections survive.
PRESET_OFFSET_KEYS = {"Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
                      "Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation"}


def user_dir():
    d = os.path.join(data_dir(), "looks")
    os.makedirs(d, exist_ok=True)
    return d


def _slug(name):
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "look"


def list_looks():
    looks = []
    for folder, builtin in ((BUILTIN_DIR, True), (user_dir(), False)):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(folder, fn), encoding="utf-8-sig") as f:
                        look = json.load(f)
                    look["builtin"] = builtin
                    look["file"] = os.path.join(folder, fn)
                    looks.append(look)
                except (OSError, ValueError):
                    pass
    return looks


def get_look(name):
    return next((l for l in list_looks() if l["name"] == name), None)


def save_user_look(look):
    path = os.path.join(user_dir(), _slug(look["name"]) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: look[k] for k in ("name", "description", "set", "offset", "masks") if k in look}, f, indent=1)
    from . import sync
    try:
        sync.sync_looks()
    except OSError:
        pass
    return path


def delete_user_look(look):
    if not look.get("builtin") and os.path.exists(look["file"]):
        os.remove(look["file"])
        from . import sync
        try:
            sync.push_look_delete(look["file"])
        except OSError:
            pass


# ---------------------------------------------------------------- applying

def _curve_eval(curve, x):
    pts = list(zip(curve[0::2], curve[1::2]))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1] if x > pts[-1][0] else pts[0][1]


def _blend_curve(a, b, s):
    if s >= 0.999:
        return list(b)
    xs = sorted(set(list(a[0::2]) + list(b[0::2]) + [0, 64, 128, 192, 255]))
    out = []
    for x in xs:
        out += [int(round(x)), int(round(_curve_eval(a, x) + s * (_curve_eval(b, x) - _curve_eval(a, x))))]
    return out


def _is_wheel_hue(key):
    return key.endswith("Hue") and (key.startswith("SplitToning") or key.startswith("ColorGrade"))


def _clamp(key, v):
    lo, hi = RANGES.get(key, (-100, 100) if key not in DEFAULTS else (-1e9, 1e9))
    if _is_wheel_hue(key):
        lo, hi = 0, 359
    return min(max(v, lo), hi)


def apply_look(settings, look, strength=1.0, dims=None):
    """Returns a new settings dict with the look blended in at the given strength (0-2).
    dims: the photo's (width, height), accepted for callers that pass it; gradients use image fractions."""
    if not look or strength <= 0:
        return settings
    s = dict(settings)
    for k, v in (look.get("set") or {}).items():
        if k in CURVE_KEYS:
            base = s.get(k) if isinstance(s.get(k), list) and len(s.get(k)) >= 4 else IDENTITY_CURVE
            s[k] = _blend_curve(base, v, min(strength, 1.0))
            s["ToneCurveName2012"] = "Custom"
        elif isinstance(v, bool) or isinstance(v, str):
            if strength >= 0.5:
                s[k] = v
        elif isinstance(v, (int, float)):
            base = s.get(k, DEFAULTS.get(k, 0))
            base = base if isinstance(base, (int, float)) and not isinstance(base, bool) else DEFAULTS.get(k, 0)
            val = base + strength * (v - base)
            if _is_wheel_hue(k):  # colour-wheel hues aren't blended, just set
                val = v
            s[k] = round(_clamp(k, val), 2) if k == "Exposure2012" else int(round(_clamp(k, val)))
    for k, d in (look.get("offset") or {}).items():
        if k in ("Temperature", "Tint") and k not in s:
            continue  # no white balance to shift (panel unchecked / Look only): keep the photo's own
        base = s.get(k, 0)
        if isinstance(base, bool) or not isinstance(base, (int, float)):
            base = 0
        val = _clamp(k, base + strength * d)
        s[k] = round(val, 2) if k == "Exposure2012" else int(round(val))
        if k in ("Temperature", "Tint"):
            s["WhiteBalance"] = "Custom"
    for m in look.get("masks") or []:  # local effects, e.g. a light leak: {"name", "zero", "full", "local"}
        vals = {k: round(_clamp_local(v * strength), 4) for k, v in (m.get("local") or {}).items()}
        s["MaskGroupBasedCorrections"] = list(s.get("MaskGroupBasedCorrections") or []) + [
            tools.build_gradient_group(m.get("name") or look.get("name", "Look"), list(m["zero"]), list(m["full"]), vals)]
    return s


def strip_look_offsets(settings, look, strength=1.0):
    """Removes a Look's offset shifts and set overrides from a photo's final Lightroom settings, so training a
    natural profile on a Look-edited shoot only learns the user's own exposure/WB/tone choices."""
    if not look or strength <= 0:
        return settings
    s = dict(settings)
    for k, d in (look.get("offset") or {}).items():
        if k in s and isinstance(s[k], (int, float)) and not isinstance(s[k], bool):
            val = _clamp(k, float(s[k]) - strength * float(d))
            s[k] = round(val, 2) if k == "Exposure2012" else int(round(val))
    for k in (look.get("set") or {}):
        s.pop(k, None)
    return s


def _clamp_local(v):
    return min(max(v, -1.0), 1.0)


# ---------------------------------------------------------------- Lightroom preset import

CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) and "." not in v else f
    except (TypeError, ValueError):
        return None


_COLORS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
# Settings that describe a style (never per-photo exposure/white balance, lens, crop or masks).
STYLE_KEYS = set(CURVE_KEYS) | {f"{a}Adjustment{c}" for a in ("Hue", "Saturation", "Luminance") for c in _COLORS} | {
    f"GrayMixer{c}" for c in _COLORS} | {
    "ConvertToGrayscale", "SplitToningShadowHue", "SplitToningShadowSaturation", "SplitToningHighlightHue",
    "SplitToningHighlightSaturation", "SplitToningBalance", "ColorGradeMidtoneHue", "ColorGradeMidtoneSat",
    "ColorGradeMidtoneLum", "ColorGradeShadowLum", "ColorGradeHighlightLum", "ColorGradeBlending",
    "ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum", "ShadowTint", "RedHue", "RedSaturation",
    "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation", "ParametricShadows", "ParametricDarks",
    "ParametricLights", "ParametricHighlights", "ParametricShadowSplit", "ParametricMidtoneSplit",
    "ParametricHighlightSplit", "PostCropVignetteAmount", "PostCropVignetteMidpoint", "PostCropVignetteFeather",
    "PostCropVignetteRoundness", "PostCropVignetteStyle", "PostCropVignetteHighlightContrast", "GrainAmount",
    "GrainSize", "GrainFrequency"}


def import_preset(path):
    """Turns a Lightroom/Camera Raw develop preset (.xmp) into a look. Returns the saved look dict."""
    root = ET.parse(path).getroot()
    values, name = {}, os.path.splitext(os.path.basename(path))[0]
    for desc in root.iter(f"{{{RDF}}}Description"):
        for attr, v in desc.attrib.items():
            if attr.startswith(f"{{{CRS}}}"):
                values[attr[len(CRS) + 2:]] = v
        for child in desc:
            if not child.tag.startswith(f"{{{CRS}}}"):
                continue
            key = child.tag[len(CRS) + 2:]
            if key == "Name":
                alt = child.find(f".//{{{RDF}}}li")
                if alt is not None and alt.text:
                    name = alt.text
            elif key in CURVE_KEYS:
                pts = []
                for li in child.iter(f"{{{RDF}}}li"):
                    pts += [int(float(p)) for p in (li.text or "").split(",")]
                if len(pts) >= 4:
                    values[key] = pts
    look_set, offset = {}, {}
    for k, v in values.items():
        if k not in STYLE_KEYS and k not in PRESET_OFFSET_KEYS:
            continue
        if isinstance(v, list):
            look_set[k] = v
        elif v in ("True", "False"):
            look_set[k] = v == "True"
        else:
            n = _num(v.lstrip("+"))
            if n is None:
                continue
            if k in PRESET_OFFSET_KEYS:
                if n:
                    offset[k] = n
            else:
                look_set[k] = n
    if len(look_set) + len(offset) < 3:
        raise ValueError("it has no color, tone or effect settings to use as a look "
                         "(it may be a camera or lens default rather than a style preset).")
    look = {"name": name, "description": f"Imported from {os.path.basename(path)}", "set": look_set, "offset": offset}
    save_user_look(look)
    return look
