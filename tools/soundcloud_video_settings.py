"""Validated render defaults shared by the GUI and clipboard worker."""
from dataclasses import asdict, dataclass
import json


MAX_VIDEO_BANDS = 30


@dataclass(frozen=True)
class SoundCloudVideoSettings:
    fps: int = 30
    resolution: int = 640
    audio_kbps: int = 128
    crf: int = 24
    preset: str = "fast"
    bands: int = 3
    intro_seconds: int = 5
    wave_background: bool = False
    wave_opacity: int = 165
    wave_line_width: int = 2
    wave_amplitude: int = 32
    wave_window_percent: int = 100
    encode_timeout: int = 300
    auto_compress: bool = True
    beat_floor_enabled: bool = True
    beat_floor_accent_every_four: bool = True
    beat_floor_x_offset: int = 0
    beat_floor_y_offset: int = -78
    beat_floor_height: int = 101
    beat_floor_far_width_percent: int = 100
    beat_floor_near_width_percent: int = 100

    def __post_init__(self):
        for name, low, high in (
            ("fps", 1, 60), ("resolution", 320, 1920),
            ("audio_kbps", 48, 320), ("crf", 0, 51), ("bands", 1, MAX_VIDEO_BANDS),
            ("intro_seconds", 0, 30), ("wave_opacity", 0, 255),
            ("wave_line_width", 1, 12), ("wave_amplitude", 1, 48), ("wave_window_percent", 25, 300),
            ("encode_timeout", 30, 7200),
            ("beat_floor_x_offset", -160, 160), ("beat_floor_y_offset", -105, 20),
            ("beat_floor_height", 12, 256),
            ("beat_floor_far_width_percent", 10, 1000), ("beat_floor_near_width_percent", 25, 150),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name}: sallittu arvo on {low}–{high}")
        if self.resolution % 2:
            raise ValueError("Resoluution pitää olla parillinen.")
        if self.preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"):
            raise ValueError("Virheellinen enkoodausnopeus.")
        if type(self.wave_background) is not bool:
            raise ValueError("Virheellinen aaltomuodon tausta-asetus.")
        if type(self.beat_floor_enabled) is not bool:
            raise ValueError("Virheellinen iskulinjojen näkyvyysasetus.")
        if type(self.beat_floor_accent_every_four) is not bool:
            raise ValueError("Virheellinen neljän iskun korostusasetus.")
        if type(self.auto_compress) is not bool:
            raise ValueError("Virheellinen automaattipakkausasetus.")

    def to_json(self):
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value):
        values = json.loads(value)
        if not isinstance(values, dict):
            raise ValueError("Videoasetusten pitää olla JSON-objekti.")
        depth = values.pop("beat_floor_depth_percent", None)
        if depth is not None and "beat_floor_height" not in values:
            if type(depth) is not int or not 20 <= depth <= 130:
                raise ValueError("Virheellinen iskulinjojen syvyys.")
            values["beat_floor_height"] = round(100.92 * depth / 100)
        return cls(**values)
