"""坐标 / 保护区几何计算 — 复刻Excel公式"""
from __future__ import annotations
import math
from core.models import Airport, QFU, Obstacle, ObstacleResult, Runway
from templates.constants import (
    PROTECTION_BASE_WIDTH, PROTECTION_SLOPE,
    PROTECTION_FULL_DIST, PROTECTION_MAX_WIDTH,
    GRADIENT_SURFACE, M_TO_FT,
)


def compute_obstacle_results(
    qfu: QFU,
    runway: Runway,
    obstacles: list[Obstacle],
    e4: float | None = None,   # 交叉跑道x轴位移 (None=use qfu.departure_x_offset)
    f4: float | None = None,   # x轴正方向旋转角度 (None=use qfu.rotation_angle)
    g4: float | None = None,   # 机场基准点沿x轴正方向位移 (None=use qfu.arp_offset)
    e6: float | None = None,   # 跑道中心沿y轴位移 (None=use qfu.lateral_offset)
    f6: float | None = None,   # 离场转弯角 (None=use qfu.departure_turn_angle)
    d5_override: float | None = None,  # 离地端标高(默认用对端QFU标高)
    main_rwy_length: int | None = None,  # 主跑道长度(默认用当前跑道)
) -> list[ObstacleResult]:
    """
    对给定QFU方向, 计算所有障碍物的分析结果.
    复刻Excel公式 B-T列.
    """
    d3 = float(main_rwy_length or runway.max_length)  # 跑道长度
    d4 = _get_qfu_heading(qfu)      # 此方向磁方位
    # D5 = 离地端标高(对端QFU入口标高)
    if d5_override is not None:
        d5 = d5_override
    else:
        d5 = _get_departure_elevation(qfu, runway)
    d6 = float(qfu.clearway)        # 净空道

    # Use QFU fields as defaults if explicit params not given
    _e4 = e4 if e4 is not None else qfu.departure_x_offset
    _f4 = f4 if f4 is not None else qfu.rotation_angle
    _g4 = g4 if g4 is not None else qfu.arp_offset
    _e6 = e6 if e6 is not None else qfu.lateral_offset
    _f6 = f6 if f6 is not None else qfu.departure_turn_angle

    results: list[ObstacleResult] = []

    for obs in obstacles:
        r = _compute_single(obs, d3, d4, d5, d6, _e4, _f4, _g4, _e6, _f6)
        results.append(r)

    return results


def _compute_single(
    obs: Obstacle,
    d3: float,  # 跑道长
    d4: float,  # 磁方位
    d5: float,  # 离地端标高
    d6: float,  # 净空道
    e4: float,  # 交叉跑道x位移
    f4: float,  # 旋转角
    g4: float,  # 基准点x位移
    e6: float,  # y位移
    f6: float,  # 离场转弯角
) -> ObstacleResult:
    c = float(obs.bearing)      # C: 磁方位(度)
    d = float(obs.distance)     # D: 距离(m)
    e = obs.elevation_m         # E: 海拔高度(m)

    # H: 方位差 = C - D4 - F4
    # 注意: d4 = 实际QFU方位(=D4+F4), 所以Python侧直接 c - d4
    # XLSX公式: =C-$D$4-$F$4 其中 D4=d4-f4(参考跑道方位)
    h = c - d4

    # I: X = D*cos(H*pi/180) - E4 + G4 - D3/2
    i_val = d * math.cos(math.radians(h)) - e4 + g4 - d3 / 2.0

    # J: Y = D*sin(H*pi/180) + E6
    j_val = d * math.sin(math.radians(h)) + e6

    # N: 角度(弧度) = |atan2(I, J) - F6*pi/180|
    # Excel ATAN2(x_num, y_num) = Python math.atan2(y_num, x_num)
    n = abs(math.atan2(j_val, i_val) - f6 * math.pi / 180.0)

    # 极径
    r_mag = math.sqrt(i_val ** 2 + j_val ** 2)

    # O: x(沿离场路径) = sqrt(I²+J²) * cos(N)
    o_val = r_mag * math.cos(n)

    # P: y(垂直离场路径) = |sqrt(I²+J²) * sin(N)|
    p_val = abs(r_mag * math.sin(n))

    # L: DIST = INT(O)
    l_val = int(o_val)

    # M: HT = E - D5
    m_val = e - d5

    # F: 1.2%梯度面高度 = D5 + (O - D6) * 0.012
    f_val = d5 + (o_val - d6) * GRADIENT_SURFACE

    # Q: 包线 = IF((|O|-D6)>6480, 900, 90+0.125*(|O|-D6))
    od = abs(o_val) - d6
    if od > PROTECTION_FULL_DIST:
        q_val = PROTECTION_MAX_WIDTH
    else:
        q_val = PROTECTION_BASE_WIDTH + PROTECTION_SLOPE * od

    # R: 保护区 = IF(AND(|P|<|Q|, O>0), "是", "否")
    r_in = abs(p_val) < abs(q_val) and o_val > 0

    # G: 是否穿过 = IF(AND(E>=F, S>0), "是", "否")
    # 这里S=L=INT(O), 所以S>0等价于O>0(基本)
    s_val = l_val
    g_pass = (e >= f_val) and (s_val > 0)

    # K: 是否为障碍物 = IF(AND(G="是", R="是"), "是", "否")
    k_is = g_pass and r_in

    result = ObstacleResult(
        obstacle=obs,
        dist_from_end=s_val,
        ht_above_end=m_val,
        is_obstacle=k_is,
        is_shielded=False,
        o_val=o_val,
        p_val=p_val,
    )
    return result


def _get_qfu_heading(qfu: QFU) -> float:
    """获取QFU磁方位: 优先用已解析的值, 否则从ident粗估"""
    if qfu.magnetic_heading:
        return float(qfu.magnetic_heading)
    # 交叉起飞点: 从parent_magnetic_heading (在解析时设置)
    if hasattr(qfu, 'parent_magnetic_heading') and qfu.parent_magnetic_heading:
        return float(qfu.parent_magnetic_heading)
    ident = qfu.ident.split()[0] if " " in qfu.ident else qfu.ident
    num_str = ""
    for ch in ident:
        if ch.isdigit():
            num_str += ch
        else:
            break
    if num_str:
        return int(num_str) * 10
    return 0


def _get_departure_elevation(qfu: QFU, runway: Runway) -> float:
    """离地端标高 = 对端QFU的入口标高"""
    main_qfus = runway.main_qfus
    if len(main_qfus) >= 2:
        # 对于主QFU, 直接用对端
        if qfu.ident == main_qfus[0].ident:
            opp = main_qfus[1]
            if opp.threshold_elevation > 0:
                return opp.threshold_elevation
        elif qfu.ident == main_qfus[1].ident:
            opp = main_qfus[0]
            if opp.threshold_elevation > 0:
                return opp.threshold_elevation
        else:
            # 交叉起飞点: 使用ident前缀匹配父QFU, 取其对端标高
            parent_ident = qfu.ident.split()[0] if " " in qfu.ident else qfu.ident
            if parent_ident == main_qfus[0].ident:
                opp = main_qfus[1]
            elif parent_ident == main_qfus[1].ident:
                opp = main_qfus[0]
            else:
                opp = None
            if opp and opp.threshold_elevation > 0:
                return opp.threshold_elevation
    return qfu.threshold_elevation


def compute_ht_ft(ht_m: float) -> int:
    """相对末端高(m) -> 英尺整数(ROUNDUP)"""
    return math.ceil(ht_m * M_TO_FT)


def apply_shielding(results: list[ObstacleResult], angle_threshold_deg: float = 1.0) -> None:
    """
    检测被遮蔽的障碍物并标记 is_shielded=True.

    规则: 障碍物A被障碍物B遮蔽, 当且仅当:
    1. B更靠近离场端 (O_B < O_A)
    2. B的高度梯度更陡 (HT_B/O_B > HT_A/O_A)
    3. 两者在类似的方位角方向上 (角度差 < threshold)
    """
    detected = [r for r in results if r.is_obstacle and r.o_val > 0]

    for a in detected:
        grad_a = a.ht_above_end / a.o_val if a.o_val > 0 else 0
        angle_a = math.degrees(math.atan2(a.p_val, a.o_val))
        for b in detected:
            if b is a:
                continue
            if b.o_val >= a.o_val:
                continue  # B must be closer
            if b.ht_above_end < a.ht_above_end:
                continue  # B must be at least as tall as A
            grad_b = b.ht_above_end / b.o_val if b.o_val > 0 else 0
            if grad_b <= grad_a:
                continue  # B must have steeper gradient
            angle_b = math.degrees(math.atan2(b.p_val, b.o_val))
            if abs(angle_a - angle_b) < angle_threshold_deg:
                a.is_shielded = True
                break
