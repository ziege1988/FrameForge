"""Turns raw metrics into comparable scores, verdicts, reasons and recommendations.

Scoring philosophy
------------------
* Absolute metrics where a physical target exists (exposure, clipping,
  tracking stability, object completeness).
* Relative metrics where only a comparison is meaningful (sharpness, contrast,
  directional blur): each file is compared with the *session median* on a
  logarithmic scale, ``score = 50 + 50·tanh(ln(value/median)/scale)``.
  This is robust for small and large sessions alike.
* If a component cannot be judged (e.g. sharpness of a single file without
  comparison) it is left out and the remaining weights are renormalised – the
  reason list states this explicitly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .profiles import Profile

COMPONENT_LABELS = {
    "sharpness": "Schärfe",
    "local": "Lokale Qualität",
    "contrast": "Kontrast",
    "noise": "Rauschen / SNR",
    "exposure": "Belichtung",
    "stability": "Bildstabilität",
    "motion": "Bewegungsunschärfe",
}

VERDICT_RECOMMENDED = "Empfohlen"
VERDICT_CONDITIONAL = "Bedingt geeignet"
VERDICT_REJECT = "Abgelehnt"
VERDICT_ERROR = "Fehler"


@dataclass
class Reason:
    kind: str  # "plus", "minus", "info"
    text: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text}


@dataclass
class Assessment:
    components: dict[str, float | None] = field(default_factory=dict)
    score: float = 0.0
    verdict: str = VERDICT_CONDITIONAL
    potential: str = "mittel"
    reasons: list[Reason] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""


def component_label(key: str, profile: Profile | None = None) -> str:
    if profile is not None and key in profile.labels:
        return profile.labels[key]
    return COMPONENT_LABELS[key]


# ---------------------------------------------------------------------------
# Frame level
# ---------------------------------------------------------------------------

def _robust_top(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 1.0
    return float(np.percentile(finite, 99)) or 1.0


def combined_sharpness(sharpness, tenengrad):
    """Laplacian based sharpness dominates; Tenengrad (edge strength) stabilises it."""
    return np.power(np.maximum(sharpness, 0), 0.75) * np.power(np.maximum(tenengrad, 0), 0.25)


def frame_quality(arrays: dict[str, np.ndarray], profile_key: str = "planet") -> np.ndarray:
    """Quality 0..100 per frame relative to the best frames of the same file."""
    if profile_key == "deepsky":
        fwhm = arrays["fwhm"]
        best = np.nanpercentile(fwhm, 1) if np.isfinite(fwhm).any() else 1.0
        s = np.where(np.isfinite(fwhm), np.clip(best / np.where(fwhm > 0, fwhm, np.inf), 0, 1), 0)
        stars = arrays["star_count"]
        t = np.clip(stars / _robust_top(stars), 0, 1)
        ecc = np.nan_to_num(arrays["eccentricity"], nan=1.0)
        e = np.clip((0.75 - ecc) / 0.35, 0, 1)
        q = 0.55 * s + 0.25 * t + 0.20 * e
        q = q * np.where(arrays["low_signal"] > 0, 0.1, 1.0)
        return np.clip(q * 100.0, 0, 100).astype(np.float32)
    sharp = combined_sharpness(arrays["sharpness"], arrays["tenengrad"])
    s = np.clip(sharp / _robust_top(sharp), 0, 1.2)
    c = np.clip(arrays["contrast"] / _robust_top(arrays["contrast"]), 0, 1.2)
    u = np.clip(arrays["uniformity"], 0, 1)
    q = 0.85 * s + 0.10 * c + 0.05 * u
    # Penalise brightness drops (clouds), lost objects and empty frames
    signal = arrays["signal"]
    med = float(np.median(signal)) if signal.size else 0.0
    if med > 0:
        ratio = signal / med
        q = q * np.where(ratio < 0.6, np.clip(ratio / 0.6, 0, 1), 1.0)
    q = q * np.where(arrays["touches_edge"] > 0, 0.5, 1.0)
    q = q * np.where(arrays["low_signal"] > 0, 0.1, 1.0)
    return np.clip(q * 100.0, 0, 100).astype(np.float32)


def recommend_selection(quality: np.ndarray, frame_count: int) -> tuple[float, str]:
    """Suggest the fraction of frames to stack and explain why."""
    if quality.size <= 1 or frame_count <= 1:
        return 1.0, "Einzelbild – keine Frame-Selektion nötig."
    top = float(np.percentile(quality, 99))
    threshold = 0.8 * top
    frac = float(np.mean(quality >= threshold))
    reason = f"{frac * 100:.0f} % der Frames liegen innerhalb von 20 % der Spitzenqualität."
    min_frac = min(1.0, 50.0 / frame_count)
    lower = max(0.05, min_frac)
    clamped = float(np.clip(frac, lower, max(0.6, lower)))
    if clamped > frac + 1e-9:
        reason += f" Für ein ausreichendes Signal-Rausch-Verhältnis werden mindestens {clamped * 100:.0f} % empfohlen."
    elif clamped < frac - 1e-9:
        reason += " Auf 60 % begrenzt, damit schwächere Frames das Ergebnis nicht verwässern."
    return clamped, reason


# ---------------------------------------------------------------------------
# Session level
# ---------------------------------------------------------------------------

def _relative(value: float, median: float, scale: float, higher_is_better: bool = True) -> float:
    if not (value > 0 and median > 0):
        return 50.0
    d = math.log(value / median)
    if not higher_is_better:
        d = -d
    return 50.0 + 50.0 * math.tanh(d / scale)


def _exposure_score(agg: dict, profile: Profile) -> float:
    lo, hi = profile.exposure_target
    p = agg["peak"]
    if p < lo:
        base = 100.0 * (max(p, 0.0) / lo) ** 1.5
    elif p > hi:
        base = 100.0 - 40.0 * min(1.0, (p - hi) / max(1.0 - hi, 1e-3))
    else:
        base = 100.0
    excess = agg["clip_high"] - profile.clip_tolerance
    penalty = min(70.0, 1500.0 * excess) if excess > 0 else 0.0
    if agg.get("surface") and agg["clip_low"] > 0.05:
        penalty += min(20.0, 100.0 * (agg["clip_low"] - 0.05))
    return float(max(0.0, base - penalty))


def _stability_score(agg: dict, profile: Profile) -> float | None:
    parts = []
    if agg["is_video"]:
        jr = agg["jitter_rel"]
        parts.append(100.0 * float(np.clip(1.0 - (jr - 0.01) / 0.07, 0.0, 1.0)))
    score = parts[0] if parts else (100.0 if profile.object_must_be_complete else None)
    if score is None:
        return None
    if profile.object_must_be_complete:
        score -= 100.0 * agg["edge_fraction"]
    if agg["is_video"]:
        score -= 50.0 * agg["dropout_fraction"]
    return float(max(0.0, score))


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _num(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


_PHRASES = {
    # key: (good, bad)
    "sharpness": ("sehr gute Schärfe", "unscharf"),
    "local": ("gleichmäßige Schärfe im Feld", "ungleichmäßige Schärfe"),
    "contrast": ("guter Kontrast", "geringer Kontrast"),
    "noise": ("niedriges Rauschen", "starkes Rauschen"),
    "exposure": ("gute Belichtung", "Belichtungsproblem"),
    "stability": ("stabile Bildlage", "Bildunruhe"),
    "motion": ("keine Bewegungsunschärfe", "Bewegungsunschärfe"),
}
_PHRASES_DEEPSKY = {
    "sharpness": ("kleine FWHM", "große FWHM (unscharf)"),
    "local": ("gleichmäßiges Bildfeld", "ungleichmäßiges Bildfeld"),
    "contrast": ("gute Transparenz", "wenige Sterne (Wolken/Dunst?)"),
    "noise": ("niedriges Rauschen", "heller Hintergrund / Rauschen"),
    "exposure": ("gute Belichtung", "Belichtungsproblem"),
    "stability": ("stabile Bildlage", "Bildunruhe"),
    "motion": ("runde Sterne", "gestreckte Sterne"),
}


def short_summary(components: dict, verdict: str, profile: Profile, agg: dict | None = None) -> str:
    """One-line justification for tables (e.g. "Sehr gute Schärfe, niedriges Rauschen")."""
    phrases = _PHRASES_DEEPSKY if profile.key == "deepsky" else _PHRASES
    avail = [(k, v) for k, v in components.items() if v is not None and k in phrases]
    if not avail:
        return ""
    weights = profile.weights
    good = sorted((kv for kv in avail if kv[1] >= 65), key=lambda kv: -(kv[1] * weights.get(kv[0], 0.1)))
    bad = sorted((kv for kv in avail if kv[1] < 40), key=lambda kv: kv[1] - 100 * weights.get(kv[0], 0.1))

    def phrase(k, good_side):
        text = phrases[k][0 if good_side else 1]
        if k == "exposure" and not good_side and agg:
            lo, _ = profile.exposure_target
            if agg.get("clip_high", 0) > profile.clip_tolerance:
                text = "überbelichtet"
            elif agg.get("peak", 1) < lo and profile.key != "deepsky":
                text = "unterbelichtet"
        return text

    if verdict == VERDICT_RECOMMENDED:
        parts = [phrase(k, True) for k, _ in good[:2]] or ["solide Gesamtqualität"]
    elif verdict == VERDICT_REJECT:
        parts = [phrase(k, False) for k, _ in bad[:2]] or ["geringes Verarbeitungspotenzial"]
    else:
        parts = [phrase(k, True) for k, _ in good[:1]] + [phrase(k, False) for k, _ in bad[:1]]
        parts = parts or ["durchschnittliche Qualität"]
    text = ", ".join(parts)
    return text[:1].upper() + text[1:]


def assess_session(aggregates: list[dict], profile: Profile) -> list[Assessment]:
    """Score all files of a session against each other."""
    if profile.key == "deepsky":
        results = _assess_deepsky(aggregates, profile)
    else:
        results = _assess_surface(aggregates, profile)
    for a, agg in zip(results, aggregates):
        if agg is not None:
            a.summary = short_summary(a.components, a.verdict, profile, agg)
    return results


def _total(comp: dict, profile: Profile) -> float:
    weights = profile.weights
    num = sum(weights[k] * v for k, v in comp.items() if v is not None and k in weights)
    den = sum(weights[k] for k, v in comp.items() if v is not None and k in weights)
    return num / den if den else 0.0


def _assess_deepsky(aggregates: list[dict], profile: Profile) -> list[Assessment]:
    valid = [a for a in aggregates if a is not None and a.get("star_count", 0) >= 3]
    n = len(valid)

    def median_of(key: str) -> float:
        vals = [a[key] for a in valid if a.get(key) is not None and np.isfinite(a[key]) and a[key] > 0]
        return float(np.median(vals)) if vals else 0.0

    med_fwhm, med_stars = median_of("fwhm"), median_of("star_count")
    med_bg, med_snr, med_unif = median_of("background"), median_of("snr"), median_of("uniformity")
    results: list[Assessment] = []
    for agg in aggregates:
        if agg is None:
            results.append(Assessment(score=0.0, verdict=VERDICT_ERROR, potential="–"))
            continue
        comp: dict[str, float | None] = {}
        reasons: list[Reason] = []
        recs: list[str] = []
        stars = agg.get("star_count", 0)
        if stars < 3:
            reasons.append(Reason("minus", "Kaum oder keine Sterne erkannt (Wolken, Tau, Fokus verloren oder falsches Profil?)."))
            recs.append("Aussortieren – ohne messbare Sterne ist die Aufnahme für die Integration unbrauchbar.")
            results.append(Assessment(components={k: None for k in COMPONENT_LABELS}, score=0.0,
                                      verdict=VERDICT_REJECT, potential="gering", reasons=reasons, recommendations=recs))
            continue
        compare = n >= 2
        fwhm, ecc = agg["fwhm"], agg["eccentricity"]

        # Sharpness (FWHM) --------------------------------------------------
        if compare and med_fwhm:
            comp["sharpness"] = _relative(fwhm, med_fwhm, 0.3, higher_is_better=False)
            rel = (fwhm / med_fwhm - 1) * 100
            if rel <= -5:
                reasons.append(Reason("plus", f"FWHM {_num(fwhm, 2)} px – {_num(-rel, 0)} % kleiner als der Session-Median."))
            elif rel >= 5:
                reasons.append(Reason("minus", f"FWHM {_num(fwhm, 2)} px – {_num(rel, 0)} % größer als der Session-Median "
                                               "(Seeing, Fokus?)."))
                if rel >= 20:
                    recs.append("Deutlich größere Sterne: Fokus prüfen (Temperaturdrift) bzw. Autofokus-Intervall verkürzen.")
            else:
                reasons.append(Reason("info", f"FWHM {_num(fwhm, 2)} px – im Bereich des Session-Medians."))
        else:
            comp["sharpness"] = None
            reasons.append(Reason("info", f"FWHM {_num(fwhm, 2)} px – ohne Vergleichsaufnahmen nicht bewertbar "
                                          "(abhängig von Brennweite und Pixelgröße)."))

        # Field uniformity --------------------------------------------------
        unif = agg["uniformity"]
        comp["local"] = 0.5 * 100 * unif + 0.5 * _relative(unif, med_unif, 0.15) if compare and med_unif else 100 * unif
        if unif < 0.75:
            reasons.append(Reason("minus", "Sterngröße variiert stark über das Bildfeld (Verkippung, Bildfeldwölbung, Koma?)."))
            recs.append("Ungleichmäßiges Bildfeld: Sensorverkippung, Backfocus/Flattener-Abstand prüfen.")

        # Transparency (star count) --------------------------------------
        if compare and med_stars:
            comp["contrast"] = _relative(stars, med_stars, 0.3)
            ratio = stars / med_stars
            if ratio < 0.7:
                reasons.append(Reason("minus", f"Nur {stars} Sterne erkannt ({_num((1 - ratio) * 100, 0)} % weniger als üblich) "
                                               "– Wolken, Dunst oder Tau?"))
            else:
                reasons.append(Reason("plus" if ratio >= 0.95 else "info", f"{stars} Sterne erkannt."))
        else:
            comp["contrast"] = None
            reasons.append(Reason("info", f"{stars} Sterne erkannt."))

        # Noise / background ---------------------------------------------
        bg = agg["background"]
        abs_noise = 100.0 * (1.0 - math.exp(-agg["snr"] / 30.0))
        if compare and med_bg:
            comp["noise"] = 0.5 * _relative(agg["snr"], med_snr, 0.4) + 0.5 * _relative(bg, med_bg, 0.3, False)
            if bg > 1.3 * med_bg:
                reasons.append(Reason("minus", f"Himmelshintergrund {_num((bg / med_bg - 1) * 100, 0)} % heller als der Median "
                                               "(Mond, Lichtverschmutzung, Dämmerung, Wolken?)."))
                recs.append("Subs mit deutlich hellerem Hintergrund nur verwenden, wenn genug Material vorhanden ist; "
                            "Gradientenentfernung einplanen.")
        else:
            comp["noise"] = abs_noise
        reasons.append(Reason("info", f"Stern-SNR (Median) ≈ {_num(agg['snr'], 0)}, Hintergrund {_pct(bg)}."))

        # Exposure ------------------------------------------------------
        lo, hi = profile.exposure_target
        exp = 100.0
        if bg < lo:
            exp = 100.0 * max(bg, 0.0) / lo
            reasons.append(Reason("minus", f"Hintergrund sehr dunkel ({_pct(bg)}) – Signal nahe am Ausleserauschen."))
            recs.append("Belichtungszeit oder Gain erhöhen, sodass der Hintergrund deutlich vom linken Histogrammrand abrückt.")
        elif bg > hi:
            exp = max(0.0, 100.0 - 200.0 * (bg - hi))
            reasons.append(Reason("minus", f"Hintergrund sehr hell ({_pct(bg)}) – Dynamikumfang geht verloren."))
        if agg["clip_low"] > 0.01:
            exp -= min(40.0, 400.0 * agg["clip_low"])
            reasons.append(Reason("minus", f"{_pct(agg['clip_low'])} der Pixel abgeschnitten (schwarz) – Offset zu niedrig?"))
        if agg["clip_high"] > profile.clip_tolerance:
            exp -= min(30.0, 3000.0 * (agg["clip_high"] - profile.clip_tolerance))
            reasons.append(Reason("info", f"{_pct(agg['clip_high'])} der Pixel gesättigt (helle Sterne/Kerne)."))
        comp["exposure"] = max(0.0, exp)

        # Stability (only for cubes/videos) ------------------------------
        comp["stability"] = _stability_score(agg, profile) if agg["is_video"] else None

        # Tracking (eccentricity) ----------------------------------------
        comp["motion"] = 100.0 * float(np.clip((0.7 - ecc) / 0.3, 0.0, 1.0))
        if ecc >= 0.55:
            reasons.append(Reason("minus", f"Gestreckte Sterne (Exzentrizität {_num(ecc, 2)}, Richtung ≈ {agg['blur_angle']:.0f}°)."))
            recs.append("Gestreckte Sterne: Nachführung/Guiding, Ausbalancierung, Wind und Kabelzug prüfen.")
        else:
            reasons.append(Reason("plus", f"Runde Sterne (Exzentrizität {_num(ecc, 2)})."))

        score = _total(comp, profile)
        verdict = VERDICT_RECOMMENDED if score >= 65 else VERDICT_CONDITIONAL if score >= 45 else VERDICT_REJECT
        if ecc >= 0.7:
            verdict = VERDICT_REJECT
        if compare and med_stars and stars < 0.5 * med_stars:
            verdict = VERDICT_REJECT
            reasons.append(Reason("minus", "Weniger als die Hälfte der üblichen Sterne – Transparenz stark reduziert."))
        elif compare and med_stars and med_bg and stars < 0.75 * med_stars and bg > 1.5 * med_bg:
            verdict = VERDICT_REJECT
            reasons.append(Reason("minus", "Weniger Sterne bei deutlich hellerem Hintergrund – typisch für Wolken oder Dunst."))
        if compare and med_fwhm and fwhm >= 1.35 * med_fwhm:
            verdict = VERDICT_REJECT
            reasons.append(Reason("minus", "FWHM mehr als 35 % über dem Median – würde das Integrationsergebnis verschlechtern."))
        potential = "hoch" if score >= 70 else "mittel" if score >= 50 else "gering"
        if verdict == VERDICT_REJECT:
            recs.insert(0, "Nicht in die Integration aufnehmen.")
        results.append(Assessment(components=comp, score=round(float(score), 1), verdict=verdict,
                                  potential=potential, reasons=reasons, recommendations=recs))
    return results


def _assess_surface(aggregates: list[dict], profile: Profile) -> list[Assessment]:
    valid = [a for a in aggregates if a is not None]
    n = len(valid)

    def median_of(key: str) -> float:
        vals = [a[key] for a in valid if a.get(key) is not None and a[key] > 0]
        return float(np.median(vals)) if vals else 0.0

    med_sharp = median_of("sharp_combined")
    med_contrast = median_of("contrast")
    med_snr = median_of("snr_stack")
    med_coh = median_of("coherence")
    med_unif = median_of("uniformity")

    results: list[Assessment] = []
    for agg in aggregates:
        if agg is None:
            results.append(Assessment(score=0.0, verdict=VERDICT_ERROR, potential="–"))
            continue
        comp: dict[str, float | None] = {}
        reasons: list[Reason] = []
        recs: list[str] = []
        compare = n >= 2

        # Sharpness ------------------------------------------------------
        if compare:
            comp["sharpness"] = _relative(agg["sharp_combined"], med_sharp, 0.25)
            ratio = agg["sharp_combined"] / med_sharp if med_sharp else 1.0
            if ratio >= 1.05:
                reasons.append(Reason("plus", f"Schärfe {_num((ratio - 1) * 100, 0)} % über dem Median der Session."))
            elif ratio <= 0.95:
                reasons.append(Reason("minus", f"Schärfe {_num((1 - ratio) * 100, 0)} % unter dem Median der Session."))
            else:
                reasons.append(Reason("info", "Schärfe im Bereich des Session-Medians."))
        else:
            comp["sharpness"] = None
            reasons.append(Reason("info", "Schärfe kann ohne Vergleichsaufnahmen nicht absolut bewertet werden – "
                                          "für ein Ranking mehrere Dateien derselben Session analysieren."))

        # Local quality --------------------------------------------------
        unif = agg["uniformity"]
        abs_local = 100.0 * unif
        comp["local"] = 0.5 * abs_local + 0.5 * _relative(unif, med_unif, 0.15) if compare else abs_local
        if unif < 0.5:
            reasons.append(Reason("minus", f"Ungleichmäßige Schärfe über das Bildfeld (Homogenität {_pct(unif)})."))
        elif unif > 0.75:
            reasons.append(Reason("plus", f"Gleichmäßige Schärfe über das Bildfeld (Homogenität {_pct(unif)})."))

        # Contrast -------------------------------------------------------
        if compare:
            comp["contrast"] = _relative(agg["contrast"], med_contrast, 0.2)
            if comp["contrast"] < 35:
                reasons.append(Reason("minus", "Kontrast deutlich unter dem Session-Durchschnitt (Dunst, Taubeschlag, Seeing?)."))
            elif comp["contrast"] > 65:
                reasons.append(Reason("plus", "Überdurchschnittlicher Kontrast."))
        else:
            comp["contrast"] = None

        # Noise / SNR ----------------------------------------------------
        snr_stack = agg["snr_stack"]
        abs_noise = 100.0 * (1.0 - math.exp(-snr_stack / 60.0))
        comp["noise"] = 0.5 * abs_noise + 0.5 * _relative(snr_stack, med_snr, 0.5) if compare else abs_noise
        if agg["is_video"]:
            reasons.append(Reason("info", f"SNR je Frame ≈ {_num(agg['snr'])}, erwartetes Stack-SNR ≈ {_num(snr_stack, 0)} "
                                          f"(bei {agg['recommended_frames']} Frames)."))
        else:
            reasons.append(Reason("info", f"Signal-Rausch-Verhältnis ≈ {_num(agg['snr'])}."))
        if snr_stack < 20:
            reasons.append(Reason("minus", "Geringes Signal-Rausch-Verhältnis."))
            recs.append("Geringes SNR: mehr Frames aufnehmen bzw. stacken oder Gain/Belichtung anpassen.")

        # Exposure -------------------------------------------------------
        comp["exposure"] = _exposure_score(agg, profile)
        lo, hi = profile.exposure_target
        if agg["peak"] < lo:
            reasons.append(Reason("minus", f"Unterbelichtet: Histogrammspitze bei {_pct(agg['peak'])} (Ziel {lo * 100:.0f}–{hi * 100:.0f} %)."))
            recs.append(f"Belichtungszeit oder Gain erhöhen – Ziel für die hellsten Objektbereiche: {lo * 100:.0f}–{hi * 100:.0f} %.")
        elif agg["peak"] > hi and agg["clip_high"] <= profile.clip_tolerance:
            reasons.append(Reason("info", f"Sehr helle Belichtung (Spitze {_pct(agg['peak'])}), noch ohne nennenswertes Clipping."))
        else:
            reasons.append(Reason("plus", f"Belichtung im Zielbereich (Spitze {_pct(agg['peak'])})."))
        if agg["clip_high"] > profile.clip_tolerance:
            reasons.append(Reason("minus", f"Überbelichtung: {_pct(agg['clip_high'])} der Objektpixel gesättigt."))
            recs.append("Überbelichtung vermeiden: Belichtungszeit oder Gain reduzieren – gesättigte Details sind unwiederbringlich.")

        # Stability ------------------------------------------------------
        comp["stability"] = _stability_score(agg, profile)
        if agg["is_video"]:
            jit = agg["jitter_px"]
            if agg["jitter_rel"] > 0.03:
                reasons.append(Reason("minus", f"Starke Bildunruhe (Streuung ≈ {_num(jit)} px um die Driftlinie)."))
                recs.append("Starke Bildunruhe: Wind, Vibrationen, Ausbalancierung und Montierung prüfen; "
                            "bei schlechtem Seeing kürzer belichten.")
            else:
                reasons.append(Reason("plus", f"Stabiles Bildfeld (Streuung ≈ {_num(jit)} px)."))
            if agg["dropout_fraction"] > 0.02:
                reasons.append(Reason("minus", f"Helligkeitseinbrüche in {_pct(agg['dropout_fraction'])} der Frames (Wolken/Dunst?)."))
                recs.append("Frames mit Helligkeitseinbrüchen (Wolken) beim Stacking ausschließen.")
        if profile.object_must_be_complete and agg["edge_fraction"] > 0:
            reasons.append(Reason("minus", f"Objekt berührt in {_pct(agg['edge_fraction'])} der Frames den Bildrand."))
            recs.append("Objekt im Bildfeld zentrieren bzw. ROI vergrößern – angeschnittene Frames sind für das Stacking unbrauchbar.")

        # Motion blur ----------------------------------------------------
        if compare and med_coh > 0:
            comp["motion"] = _relative(agg["coherence"], med_coh, 0.3, higher_is_better=False)
            if comp["motion"] < 35:
                reasons.append(Reason("minus", f"Hinweise auf gerichtete Unschärfe (Richtung ≈ {agg['blur_angle']:.0f}°)."))
                recs.append("Gerichtete Unschärfe: mögliche Ursachen sind Wind, Vibrationen, Fokussieren während der Aufnahme oder Nachführfehler.")
        else:
            comp["motion"] = None

        # Seeing variability --------------------------------------------
        if agg["is_video"] and agg["quality_cv"] > 0.25:
            reasons.append(Reason("info", f"Stark schwankendes Seeing (Variationskoeffizient der Frame-Qualität {_pct(agg['quality_cv'])})."))
            recs.append("Stark schwankendes Seeing: strenge Frame-Selektion lohnt sich besonders.")

        if profile.max_capture_s and agg.get("duration_s") and agg["duration_s"] > profile.max_capture_s:
            recs.append(
                f"Aufnahmedauer {agg['duration_s']:.0f} s: bei schnell rotierenden Planeten (Jupiter, Saturn) "
                "ohne Derotation kann Rotationsunschärfe entstehen – Faustregel: wenige Minuten je Video, "
                "abhängig von Brennweite und Planet."
            )

        score = _total(comp, profile)

        verdict = VERDICT_RECOMMENDED if score >= 65 else VERDICT_CONDITIONAL if score >= 45 else VERDICT_REJECT
        if profile.object_must_be_complete and agg["edge_fraction"] > 0.5:
            verdict = VERDICT_REJECT
            reasons.append(Reason("minus", "Mehr als die Hälfte der Frames ist angeschnitten."))
        if agg["clip_high"] > 0.05 and verdict == VERDICT_RECOMMENDED:
            verdict = VERDICT_CONDITIONAL
        if agg["low_signal_fraction"] > 0.5:
            verdict = VERDICT_REJECT
            reasons.append(Reason("minus", "Überwiegend kein verwertbares Signal (leere oder extrem dunkle Frames)."))

        potential = "hoch" if score >= 70 else "mittel" if score >= 50 else "gering"
        if agg["is_video"] and verdict != VERDICT_REJECT:
            recs.insert(0, f"Für das Stacking die besten {agg['recommended_fraction'] * 100:.0f} % verwenden "
                           f"(≈ {agg['recommended_frames']} von {agg['frame_count']} Frames). {agg['selection_reason']}")
        if verdict == VERDICT_REJECT:
            recs.insert(0, "Aussortieren empfohlen – die Datei hat im Vergleich ein geringes Verarbeitungspotenzial.")

        results.append(Assessment(components=comp, score=round(float(score), 1), verdict=verdict,
                                  potential=potential, reasons=reasons, recommendations=recs))
    return results


def session_recommendations(files: list, profile: Profile) -> list[str]:
    """High level advice for the whole session (files must be scored)."""
    ok = [f for f in files if f.error is None]
    if not ok:
        return ["Keine auswertbaren Dateien gefunden."]
    recs = []
    ranked = sorted(ok, key=lambda f: f.score, reverse=True)
    best = ranked[0]
    recs.append(f"Beste Aufnahme: {best.path.name} (Score {best.score:.0f}) – als Hauptdatensatz verwenden.")
    good = [f for f in ok if f.verdict == VERDICT_RECOMMENDED]
    reject = [f for f in ok if f.verdict == VERDICT_REJECT]
    recs.append(f"{len(good)} von {len(ok)} Dateien empfohlen, {len(reject)} zum Aussortieren vorgeschlagen.")
    if profile.key == "deepsky" and good:
        recs.append(f"Für die Integration die {len(good)} empfohlenen Subs verwenden"
                    + (", bedingt geeignete nur bei Bedarf ergänzen." if len(good) < len(ok) else "."))
    timed = [f for f in ok if f.timeline_start is not None]
    if len(timed) >= 3:
        ordered = sorted(timed, key=lambda f: f.timeline_start)
        third = max(1, len(ordered) // 3)
        first = np.mean([f.score for f in ordered[:third]])
        last = np.mean([f.score for f in ordered[-third:]])
        if last - first > 10:
            recs.append("Die Qualität hat im Verlauf der Session zugenommen (Seeing/Objekthöhe besser).")
        elif first - last > 10:
            recs.append("Die Qualität hat im Verlauf der Session abgenommen (Seeing, sinkende Objekthöhe, Taubeschlag?).")
        if profile.key == "deepsky":
            fw = [f.aggregate.get("fwhm") for f in ordered]
            if all(v and np.isfinite(v) for v in fw):
                a, b = np.mean(fw[:third]), np.mean(fw[-third:])
                if b > 1.15 * a:
                    recs.append(f"Die FWHM ist im Verlauf um {(b / a - 1) * 100:.0f} % gestiegen – möglicher Fokusdrift "
                                "(Temperatur): regelmäßig nachfokussieren.")
    if len(ok) == 1:
        recs.append("Hinweis: Für ein aussagekräftiges Ranking mehrere Aufnahmen derselben Session gemeinsam analysieren.")
    return recs
