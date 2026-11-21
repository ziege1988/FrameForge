"""Object specific evaluation profiles (Sun, Moon, planets, general)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    description: str
    #: "object" = analyse only the detected object (planet disc),
    #: "auto"   = object if it is small, otherwise the whole frame (surface shots)
    roi_mode: str
    #: Gaussian sigma (in analysis pixels) to suppress noise before measuring sharpness
    denoise_sigma: float
    #: Local quality grid (tiles per axis)
    grid: int
    #: Target range of the object's bright end (99.5th percentile, 0..1)
    exposure_target: tuple[float, float]
    #: Tolerated fraction of clipped object pixels before penalties start
    clip_tolerance: float
    #: Component weights for the session score (sum = 1)
    weights: dict[str, float] = field(default_factory=dict)
    #: Edge contact of the object is a problem (planets drifting out of the field)
    object_must_be_complete: bool = False
    #: Recommended maximum capture length in seconds (planet rotation), None = no limit
    max_capture_s: float | None = None
    #: Profile specific names of score components (e.g. "Nachführung" for deep-sky)
    labels: dict[str, str] = field(default_factory=dict)
    #: Short name of the analysed unit in texts
    unit: str = "Frames"


PROFILES: dict[str, Profile] = {
    "planet": Profile(
        key="planet",
        name="Planeten",
        description="Kleines, helles Objekt vor dunklem Hintergrund. Bewertet wird nur die Planetenscheibe.",
        roi_mode="object",
        denoise_sigma=1.0,
        grid=3,
        exposure_target=(0.45, 0.85),
        clip_tolerance=0.001,
        weights={
            "sharpness": 0.38,
            "local": 0.08,
            "contrast": 0.10,
            "noise": 0.14,
            "exposure": 0.14,
            "stability": 0.10,
            "motion": 0.06,
        },
        object_must_be_complete=True,
        max_capture_s=180.0,
    ),
    "moon": Profile(
        key="moon",
        name="Mond",
        description="Mondoberfläche oder ganze Mondscheibe. Lokale Schärfe über das Feld ist wichtig.",
        roi_mode="auto",
        denoise_sigma=1.0,
        grid=4,
        exposure_target=(0.55, 0.90),
        clip_tolerance=0.002,
        weights={
            "sharpness": 0.34,
            "local": 0.18,
            "contrast": 0.12,
            "noise": 0.10,
            "exposure": 0.14,
            "stability": 0.06,
            "motion": 0.06,
        },
    ),
    "sun": Profile(
        key="sun",
        name="Sonne",
        description="Weißlicht oder H-Alpha. Feine Strukturen (Granulation, Protuberanzen) mit geringem Kontrast.",
        roi_mode="auto",
        denoise_sigma=1.2,
        grid=4,
        exposure_target=(0.50, 0.88),
        clip_tolerance=0.002,
        weights={
            "sharpness": 0.32,
            "local": 0.18,
            "contrast": 0.16,
            "noise": 0.10,
            "exposure": 0.12,
            "stability": 0.06,
            "motion": 0.06,
        },
    ),
    "deepsky": Profile(
        key="deepsky",
        name="Deep-Sky",
        description="Einzelbelichtungen (Subs/Lights) von Nebeln, Galaxien, Sternhaufen. "
                    "Bewertet werden Sternform (FWHM, Elongation), Sternanzahl, Himmelshintergrund und Rauschen.",
        roi_mode="auto",
        denoise_sigma=1.0,
        grid=3,
        exposure_target=(0.02, 0.35),  # target range of the sky background
        clip_tolerance=0.002,
        weights={
            "sharpness": 0.28,
            "local": 0.08,
            "contrast": 0.16,
            "noise": 0.16,
            "exposure": 0.08,
            "stability": 0.04,
            "motion": 0.20,
        },
        labels={
            "sharpness": "Schärfe (FWHM)",
            "local": "Bildfeld",
            "contrast": "Transparenz",
            "noise": "Rauschen / Hintergrund",
            "exposure": "Belichtung",
            "stability": "Bildstabilität",
            "motion": "Nachführung",
        },
        unit="Subs",
    ),
    "general": Profile(
        key="general",
        name="Allgemein",
        description="Neutrales Profil für sonstige Aufnahmen.",
        roi_mode="auto",
        denoise_sigma=1.0,
        grid=4,
        exposure_target=(0.30, 0.90),
        clip_tolerance=0.005,
        weights={
            "sharpness": 0.34,
            "local": 0.12,
            "contrast": 0.12,
            "noise": 0.16,
            "exposure": 0.12,
            "stability": 0.08,
            "motion": 0.06,
        },
    ),
}

DEFAULT_PROFILE = "planet"


def get_profile(key: str) -> Profile:
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"Unbekanntes Profil: {key}. Verfügbar: {', '.join(PROFILES)}") from exc
