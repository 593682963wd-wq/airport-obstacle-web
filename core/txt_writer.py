"""PEP TXT 格式输出"""
from __future__ import annotations
import math
from core.models import Airport, Runway, QFU, ObstacleResult
from templates.constants import (
    VERSION, STATE, ENTRY_ANGLE,
    GROOVED_PFC_SURFACE_TO, GROOVED_PFC_STOPWAY, RUNWAY_PAVEMENT,
    GROOVED_PFC_SURFACE_LD, SPD_OPTI_FLAG, MAX_GA_KVS, MAX_ACC_DIST,
    CLB_SPEED_LIMIT, INITIAL_CLB_SPEED, SPEED_LIMIT_ALT,
    APPROACH_SLOPE, INCREMENT_GA_HEIGHT,
    M_TO_FT, FT_TO_M,
)


def generate_txt(airport: Airport) -> str:
    """生成PEP格式TXT字符串"""
    lines: list[str] = []
    lines.append(f"Version={VERSION};")
    lines.append("Airport;")
    _airport_block(lines, airport)
    for rwy in airport.runways:
        _runway_block(lines, rwy, airport)
    lines.append("End;")
    return "\n".join(lines) + "\n"


def _airport_block(lines: list[str], ap: Airport):
    _field(lines, 1, "Name", ap.name)
    _field(lines, 1, "State", STATE)
    _field(lines, 1, "City", ap.city)
    _field(lines, 1, "ICAO", ap.icao)
    _field(lines, 1, "IATA", ap.iata)
    _field(lines, 1, "Latitude", "")
    _field(lines, 1, "Longitude", "")
    _field(lines, 1, "Elevation", _fmt_elev(ap.elevation))
    _field(lines, 1, "MagneticVariation", ap.magnetic_variation)
    _field(lines, 1, "Comments", "")
    _field(lines, 1, "LastUpdate", ap.last_update)


def _runway_block(lines: list[str], rwy: Runway, ap: Airport):
    lines.append("   Runway;")
    _field(lines, 2, "MagneticHeading", rwy.magnetic_heading)
    _field(lines, 2, "MagneticHeadingDate", rwy.magnetic_heading_date)
    _field(lines, 2, "Strength", rwy.strength)
    _field(lines, 2, "MaxLength", rwy.max_length)
    _field(lines, 2, "Width", rwy.width)
    _field(lines, 2, "Shoulder", "")
    _field(lines, 2, "Comments", rwy.comments)
    _field(lines, 2, "LastUpdate", rwy.last_update)

    for qfu in rwy.qfus:
        if qfu.tora == 0:
            continue  # 跳过无TORA的QFU(如反向无起飞数据)
        _qfu_block(lines, qfu, ap)

    lines.append("   End;")


def _qfu_block(lines: list[str], qfu: QFU, ap: Airport):
    lines.append("      QFU;")
    _field(lines, 3, "Ident", qfu.txt_ident)
    _field(lines, 3, "ASDA", qfu.asda)
    _field(lines, 3, "LDA", qfu.lda)
    _field(lines, 3, "TODA", qfu.toda)
    _field(lines, 3, "TORA", qfu.tora)
    _field(lines, 3, "TakeoffShift", qfu.takeoff_shift)
    _field(lines, 3, "Slope", _fmt_slope(qfu.slope))
    _field(lines, 3, "EntryAngle", ENTRY_ANGLE)
    # PEP TXT 输出统一使用机场标高作为 ThresholdElevation
    _field(lines, 3, "ThresholdElevation", _fmt_elev(ap.elevation))
    _field(lines, 3, "ThresholdLatitude", "")
    _field(lines, 3, "ThresholdLongitude", "")
    _field(lines, 3, "GlideSlope", _fmt_glide_slope(qfu.glide_slope))
    _field(lines, 3, "GroovedPFCSurfaceTO", GROOVED_PFC_SURFACE_TO)
    _field(lines, 3, "GroovedPFCStopway", GROOVED_PFC_STOPWAY)
    _field(lines, 3, "RunwayPavement", RUNWAY_PAVEMENT)
    _field(lines, 3, "GroovedPFCSurfaceLD", GROOVED_PFC_SURFACE_LD)
    _field(lines, 3, "TOComments", "")
    _field(lines, 3, "LDComments", "")
    _field(lines, 3, "LastUpdate", qfu.last_update)
    _field(lines, 3, "GAMethodFlag", qfu.ga_method_flag)
    _field(lines, 3, "ApproachSlope",
           qfu.approach_slope if qfu.approach_slope is not None else APPROACH_SLOPE)
    _field(lines, 3, "IncrementGAHeight",
           qfu.increment_ga_height if qfu.ga_method_flag == 0 and qfu.increment_ga_height is not None else
           (INCREMENT_GA_HEIGHT if qfu.ga_method_flag == 0 else ""))
    _field(lines, 3, "TargetAltitude", "")
    _field(lines, 3, "DecisionAltitude", "")
    _field(lines, 3, "MinGAEOAccelHeight", "")
    _field(lines, 3, "SpdOptiFlag", SPD_OPTI_FLAG)
    _field(lines, 3, "MaxGAKVs", MAX_GA_KVS)
    _field(lines, 3, "MaxAccDist", MAX_ACC_DIST)
    _field(lines, 3, "TransitionAlt", "")
    _field(lines, 3, "ThrRedHeight", "")
    _field(lines, 3, "AccHeight", "")
    _field(lines, 3, "ClbSpeedLimit", CLB_SPEED_LIMIT)
    _field(lines, 3, "InitialClbSpeed", INITIAL_CLB_SPEED)
    _field(lines, 3, "SpeedLimitAlt", SPEED_LIMIT_ALT)
    _field(lines, 3, "FinalCLBSpeed", "")
    _field(lines, 3, "EntryOf", "")
    _field(lines, 3, "EntryComments", "")
    _field(lines, 3, "EntryLastUpdate", qfu.entry_last_update)
    _field(lines, 3, "V2minType", "")
    _field(lines, 3, "V2minValue", "")
    _field(lines, 3, "V2maxType", "")
    _field(lines, 3, "V2maxValue", "")
    _field(lines, 3, "MinEOAccelHeight", "")

    # Obstacle块: K=是 且未被遮蔽
    for obs_r in qfu.obstacle_results:
        if obs_r.is_obstacle and not obs_r.is_shielded:
            _obstacle_block(lines, obs_r, qfu, ap)

    lines.append("      End;")


def _obstacle_block(lines: list[str], obs_r: ObstacleResult, qfu: QFU, ap: Airport):
    """
    PEP Obstacle block.
    Distance = dist_from_end + TORA (从起飞起始点算起)
    Elevation = (ap.elevation + slope/100 * TORA) + ceil(HT * M_TO_FT) * FT_TO_M
    """
    txt_dist = obs_r.dist_from_end + qfu.tora
    # Elevation: 使用预计算值, 或现场计算
    if obs_r.txt_elevation and obs_r.txt_elevation > 0:
        txt_elev = obs_r.txt_elevation
    else:
        d5_equiv = ap.elevation + (qfu.slope / 100.0) * qfu.tora
        ht_ft = math.ceil(obs_r.ht_above_end * M_TO_FT)
        txt_elev = d5_equiv + ht_ft * FT_TO_M
    lines.append("         Obstacle;")
    _field(lines, 4, "Distance", txt_dist)
    _field(lines, 4, "Elevation", _fmt_elev(txt_elev))
    _field(lines, 4, "LateralDistance", "")
    _field(lines, 4, "Nature", "")
    _field(lines, 4, "Comments", obs_r.comment_label)
    _field(lines, 4, "LastUpdate", obs_r.obs_last_update or ap.obstacle_last_update)
    lines.append("         End;")


# ── 格式化辅助 ──────────────────────────────

def _field(lines: list[str], indent_level: int, name: str, value):
    indent = "   " * indent_level
    lines.append(f"{indent}{name}={_val(value)};")


def _val(v) -> str:
    if v is None or v == "":
        return ""
    return str(v)


def _fmt_elev(v: float) -> str:
    """标高/海拔保留至4位小数, 去掉末尾多余0"""
    if v == 0:
        return "0"
    s = f"{v:.4f}"
    # 去掉末尾多余的0, 但保留小数点后至少一位
    s = s.rstrip("0").rstrip(".")
    return s


def _fmt_slope(v: float) -> str:
    """坡度格式"""
    if v == 0:
        return "0"
    # 保留到有效位, 去掉末尾多余0
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def _fmt_glide_slope(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if v == int(v) else str(v)


def write_txt(airport: Airport, filepath: str):
    """写入TXT文件"""
    content = generate_txt(airport)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
