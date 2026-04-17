"""PEP TXT 格式解析器 — 读取 PEP 格式输入文件到 Airport 数据模型

PEP格式结构:
  Version=1;
  Airport;
    Name=MEILAN;
    ...
    Runway;
      QFU;
        Obstacle;
        End;
      End;
    End;
  End;
"""
from __future__ import annotations
import re
from core.models import Airport, Runway, QFU, Obstacle, ObstacleResult


def parse_pep_txt(filepath: str) -> Airport:
    """解析PEP格式TXT文件, 返回Airport对象."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    airport = Airport()
    idx = 0

    while idx < len(lines):
        line = lines[idx].strip().rstrip(';')
        idx += 1

        if line.startswith('Version='):
            continue

        if line == 'Airport':
            idx = _parse_airport_block(lines, idx, airport)

    return airport


def _parse_airport_block(lines: list[str], idx: int, airport: Airport) -> int:
    """解析Airport块, 返回结束行号"""
    while idx < len(lines):
        line = lines[idx].strip().rstrip(';')
        idx += 1

        if line == 'End':
            return idx

        if line == 'Runway':
            rwy = Runway()
            idx = _parse_runway_block(lines, idx, rwy, airport)
            # 跳过空跑道(MagneticHeading=0且无有效QFU)
            valid_qfus = [q for q in rwy.qfus if q.tora > 0]
            if rwy.magnetic_heading > 0 or valid_qfus:
                airport.runways.append(rwy)
            continue

        k, v = _parse_kv(line)
        if k == 'Name':
            airport.name = v
        elif k == 'City':
            airport.city = v
        elif k == 'ICAO':
            airport.icao = v
        elif k == 'IATA':
            airport.iata = v
        elif k == 'Elevation':
            airport.elevation = _float(v)
        elif k == 'MagneticVariation':
            airport.magnetic_variation = v
        elif k == 'LastUpdate':
            airport.last_update = v

    return idx


def _parse_runway_block(lines: list[str], idx: int, rwy: Runway, airport: Airport) -> int:
    """解析Runway块"""
    while idx < len(lines):
        line = lines[idx].strip().rstrip(';')
        idx += 1

        if line == 'End':
            return idx

        if line == 'QFU':
            qfu = QFU(ident='')
            idx = _parse_qfu_block(lines, idx, qfu, airport)
            rwy.qfus.append(qfu)
            continue

        k, v = _parse_kv(line)
        if k == 'MagneticHeading':
            rwy.magnetic_heading = _int(v)
        elif k == 'MagneticHeadingDate':
            rwy.magnetic_heading_date = v
        elif k == 'Strength':
            rwy.strength = v
        elif k == 'MaxLength':
            rwy.max_length = _int(v)
        elif k == 'Width':
            rwy.width = _int(v)
        elif k == 'Shoulder':
            rwy.shoulder = v
        elif k == 'Comments':
            rwy.comments = v
        elif k == 'LastUpdate':
            rwy.last_update = v

    return idx


def _parse_qfu_block(lines: list[str], idx: int, qfu: QFU, airport: Airport) -> int:
    """解析QFU块"""
    _obs_raw: list[tuple[ObstacleResult, int]] = []  # (obs_r, raw_distance)
    while idx < len(lines):
        line = lines[idx].strip().rstrip(';')
        idx += 1

        if line == 'End':
            # 后处理: dist_from_end = raw_distance - TORA
            for obs_r, raw_dist in _obs_raw:
                obs_r.dist_from_end = raw_dist - qfu.tora if qfu.tora > 0 else raw_dist
                obs_r.is_obstacle = True  # PEP中出现的障碍物即为确认障碍物
            return idx

        if line == 'Obstacle':
            obs_r = ObstacleResult(obstacle=Obstacle(seq=0, name='', bearing=0, distance=0))
            raw_dist = [0]
            idx = _parse_obstacle_block(lines, idx, obs_r, raw_dist)
            _obs_raw.append((obs_r, raw_dist[0]))
            qfu.obstacle_results.append(obs_r)
            continue

        k, v = _parse_kv(line)
        if k == 'Ident':
            qfu.ident = v
            if ' ' in v:
                qfu.is_intersection = True
        elif k == 'ASDA':
            qfu.asda = _int(v)
        elif k == 'LDA':
            qfu.lda = _int(v)
        elif k == 'TODA':
            qfu.toda = _int(v)
        elif k == 'TORA':
            qfu.tora = _int(v)
        elif k == 'TakeoffShift':
            qfu.takeoff_shift = v
        elif k == 'Slope':
            qfu.slope = _float(v)
        elif k == 'ThresholdElevation':
            qfu.threshold_elevation = _float(v)
        elif k == 'GlideSlope':
            if v:
                qfu.glide_slope = _float(v)
        elif k == 'GAMethodFlag':
            qfu.ga_method_flag = _int(v) if v else 1
        elif k == 'ApproachSlope':
            if v:
                qfu.approach_slope = _float(v)
        elif k == 'IncrementGAHeight':
            if v:
                qfu.increment_ga_height = _float(v)
        elif k == 'LastUpdate':
            qfu.last_update = v
        elif k == 'EntryLastUpdate':
            qfu.entry_last_update = v
        elif k == 'MagneticHeading':
            qfu.magnetic_heading = _int(v)

    return idx


def _parse_obstacle_block(lines: list[str], idx: int, obs_r: ObstacleResult, raw_dist: list) -> int:
    """解析Obstacle块"""
    while idx < len(lines):
        line = lines[idx].strip().rstrip(';')
        idx += 1

        if line == 'End':
            return idx

        k, v = _parse_kv(line)
        if k == 'Distance':
            raw_dist[0] = _int(v)
        elif k == 'Elevation':
            obs_r.txt_elevation = _float(v)
        elif k == 'Comments':
            obs_r.comment_label = v
            # 从Comments提取seq号: "5 A1-1" → seq=5
            m = re.match(r'(\d+)\s', v)
            if m:
                obs_r.obstacle.seq = int(m.group(1))
        elif k == 'LastUpdate':
            obs_r.obs_last_update = v
        elif k == 'Nature':
            pass  # 忽略
        elif k == 'LateralDistance':
            pass  # 忽略

    return idx


# ── 辅助函数 ──

def _parse_kv(line: str) -> tuple[str, str]:
    """解析 'Key=Value' 格式行"""
    eq = line.find('=')
    if eq < 0:
        return (line, '')
    return (line[:eq].strip(), line[eq+1:].strip())


def _float(v: str) -> float:
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def _int(v: str) -> int:
    if not v:
        return 0
    try:
        return int(float(v))
    except ValueError:
        return 0
