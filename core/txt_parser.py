"""AIP TXT 解析 — 从PDF转换的纯文本中提取 AD 2.1/2.2/2.10/2.12/2.13 数据

替代 pdf_parser.py，直接读取纯文本文件，避免 pdfplumber 依赖。
文本格式：由桌面 PDF转文本.html 工具生成的纯文本。
"""
from __future__ import annotations
import re
from typing import Optional
from core.models import Airport, Runway, QFU, Obstacle
from templates.constants import FT_TO_M, APPROACH_SLOPE, INCREMENT_GA_HEIGHT


def parse_aip_txt(filepath: str) -> Airport:
    """
    解析AIP纯文本文件, 返回Airport对象.
    提取 AD 2.1 (ICAO/IATA/名称), AD 2.2 (标高/磁差),
    AD 2.12 (跑道物理特征), AD 2.13 (申报距离), AD 2.10 (障碍物).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        all_text = f.read()

    airport = Airport()

    _parse_header(airport, all_text)
    _parse_ad22(airport, all_text)
    _parse_ad212(airport, all_text)
    _parse_ad213(airport, all_text)
    _parse_ad210(airport, all_text)

    # 交叉起飞点排序: 先第一方向后第二方向, 同方向内按TORA升序
    for rwy in airport.runways:
        main_qfus = [q for q in rwy.qfus if not q.is_intersection]
        inter_qfus = [q for q in rwy.qfus if q.is_intersection]
        if inter_qfus and len(main_qfus) >= 2:
            dir1_ident = main_qfus[0].ident
            def _sort_key(q):
                is_dir1 = q.ident.startswith(dir1_ident + " ") or q.ident == dir1_ident
                return (0 if is_dir1 else 1, q.tora)
            inter_qfus.sort(key=_sort_key)
            rwy.qfus = main_qfus + inter_qfus

    # ILS: 如果跑道上任一主方向QFU有glide_slope, 该跑道所有QFU都设置glide_slope
    for rwy in airport.runways:
        if rwy.has_ils:
            for qfu in rwy.qfus:
                if qfu.glide_slope is None:
                    qfu.glide_slope = -3

    # 根据入口标高差计算有效坡度(对多段坡度场景更准确)
    for rwy in airport.runways:
        mains = rwy.main_qfus
        if len(mains) == 2 and rwy.max_length > 0:
            t0 = mains[0].threshold_elevation
            t1 = mains[1].threshold_elevation
            if t0 > 0 and t1 > 0:
                eff_slope = round((t1 - t0) / rwy.max_length * 100, 2)
                mains[0].slope = eff_slope
                mains[1].slope = -eff_slope

    return airport


# ── AD 2.1 机场代码和名称 ──────────────────

def _parse_header(airport: Airport, text: str):
    """从文本提取ICAO/IATA/城市/名称"""
    # ICAO/IATA: "ZJHK/HAK"
    m = re.search(r'\b([A-Z]{4})/([A-Z]{3})\b', text)
    if m:
        airport.icao = m.group(1)
        airport.iata = m.group(2)

    # 英文城市/名称: "HAIKOU/Meilan"
    m = re.search(
        r'[\u4e00-\u9fff]\s*([A-Z][A-Za-z]+)\s*/\s*([A-Za-z]+)',
        text[:3000]
    )
    if m:
        airport.city = m.group(1).upper()
        airport.name = m.group(2).upper()


# ── AD 2.2 机场地理位置和管理资料 ──────────

def _parse_ad22(airport: Airport, text: str):
    """解析标高、磁差"""
    ad22_match = re.search(r'AD 2\.2.*?AD 2\.3', text, re.DOTALL)
    ad22_text = ad22_match.group() if ad22_match else text[:5000]

    # 标高: "22.6 m(75ft)"
    m_ft = re.search(r'([\d.]+)\s*m\s*\(\s*(\d+)\s*ft\s*\)', ad22_text)
    if m_ft:
        airport.elevation = round(int(m_ft.group(2)) * FT_TO_M, 4)

    # 磁差: "2°7′W(2019)" or "4°53′W"
    m = re.search(r'(\d+)[°度]\s*(\d+)?[′\'′]?\s*([WE])', ad22_text)
    if m:
        deg = int(m.group(1))
        mins = int(m.group(2)) if m.group(2) else 0
        d = m.group(3)
        airport.magnetic_variation = f"{deg:02d}{mins:02d}00{d}"


# ── AD 2.12 跑道物理特征 ──────────────────

def _parse_ad212(airport: Airport, text: str):
    """从纯文本解析跑道物理数据"""
    m_section = re.search(r'AD 2\.12.*?(?=AD 2\.13)', text, re.DOTALL)
    if not m_section:
        return
    section = m_section.group()
    lines = section.split('\n')

    qfu_data = []

    # 逐行扫描找跑道数据块
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        # 跑道号码行: "09   3600×45" 开头
        m_rwy = re.match(r'^(\d{2}[LRC]?)\s+(\d+)\s*[×xX]\s*(\d+)', line)
        if not m_rwy:
            continue

        rwy_id = m_rwy.group(1)
        length = int(m_rwy.group(2))
        width = int(m_rwy.group(3))

        # PCN: 在该行本身或前几行查找
        pcn = ""
        for j in range(max(0, i - 2), i + 1):
            m_pcn = re.search(r'(?:PCR|PCN)\s*(\d+/[A-Z]/[A-Z]/[A-Z]/[A-Z])', lines[j])
            if m_pcn:
                pcn = m_pcn.group(1)
                break

        # 磁方位: 仅在跑道号码行之后查找(避免误取上一个QFU的MAG)
        mag = 0
        for j in range(i + 1, min(i + 3, len(lines))):
            m_mag = re.search(r'(\d+)\s*°?\s*MAG', lines[j])
            if m_mag:
                mag = int(m_mag.group(1))
                break

        # 入口标高: 在该行本身和前后几行查找 THR xxm/xxft
        # 优先使用AIP原始米值(如22.6m), 而非英尺换算值(75ft=22.86m)
        thr_elev = 0.0
        for j in range(max(0, i - 2), min(i + 3, len(lines))):
            m_thr_ft = re.search(r'THR\s*([\d.]+)\s*m\s*/\s*(\d+)\s*ft', lines[j])
            if m_thr_ft:
                thr_elev = float(m_thr_ft.group(1))
                break
            m_thr_m = re.search(r'THR\s*([\d.]+)\s*m', lines[j])
            if m_thr_m:
                thr_elev = float(m_thr_m.group(1))
                break

        # ILS: 所有QFU默认GlideSlope=-3(PEP格式要求)
        glide_slope = -3

        # 坡度: 从跑道号码行本身和之后几行提取
        # 对于单段坡度(如"0.1%"), 直接取值
        # 对于多段坡度, 后续由入口标高差重新计算
        slope = 0.0
        slope_text = '\n'.join(lines[i:min(i + 3, len(lines))])
        slope_matches = re.findall(r'(-?[\d.]+)\s*%', slope_text)
        if slope_matches:
            slope = float(slope_matches[-1])

        qfu_data.append({
            'ident': rwy_id, 'length': length, 'width': width,
            'pcn': pcn, 'mag': mag, 'thr_elev': thr_elev,
            'glide_slope': glide_slope, 'slope': slope,
        })

    # 按对组建Runway(连续两个同尺寸QFU构成一条物理跑道)
    idx = 0
    while idx < len(qfu_data):
        d1 = qfu_data[idx]
        rwy = Runway()
        rwy.max_length = d1['length']
        rwy.width = d1['width']
        rwy.strength = d1['pcn']

        q1 = QFU(
            ident=d1['ident'],
            magnetic_heading=d1['mag'],
            threshold_elevation=d1['thr_elev'],
            glide_slope=d1['glide_slope'],
            slope=d1['slope'],
            ga_method_flag=0,
        )
        rwy.qfus.append(q1)

        if idx + 1 < len(qfu_data):
            d2 = qfu_data[idx + 1]
            if d2['length'] == d1['length'] and d2['width'] == d1['width']:
                q2 = QFU(
                    ident=d2['ident'],
                    magnetic_heading=d2['mag'],
                    threshold_elevation=d2['thr_elev'],
                    ga_method_flag=0,
                    glide_slope=d2['glide_slope'],
                    slope=d2['slope'],
                )
                rwy.qfus.append(q2)
                idx += 2
            else:
                idx += 1
        else:
            idx += 1

        headings = [q.magnetic_heading for q in rwy.qfus if q.magnetic_heading]
        if headings:
            rwy.magnetic_heading = min(headings)

        airport.runways.append(rwy)

    # 道肩信息
    m_shoulder = re.findall(
        r'(\d{2}[LRC]?(?:/\d{2}[LRC]?)*)\s*[：:]\s*[^；;]*?道肩[^；;]*?(?:各|宽)\s*([\d.]+)\s*m',
        section
    )
    for rwy_group, shoulder_val in m_shoulder:
        rwy_ids = re.findall(r'\d{2}[LRC]?', rwy_group)
        for rwy in airport.runways:
            rwy_idents = {q.ident for q in rwy.qfus}
            if any(rid in rwy_idents for rid in rwy_ids):
                rwy.shoulder = shoulder_val
                break


# ── AD 2.13 申报距离 ──────────────────────

def _parse_ad213(airport: Airport, text: str):
    """解析申报距离"""
    m_section = re.search(r'AD 2\.13.*?(?=AD 2\.14|$)', text, re.DOTALL)
    if not m_section:
        return
    section = m_section.group()

    pattern = re.compile(
        r'^(\d{2}[LRC]?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*?)$',
        re.MULTILINE
    )

    for m in pattern.finditer(section):
        rwy_id = m.group(1)
        tora = int(m.group(2))
        toda = int(m.group(3))
        asda = int(m.group(4))
        lda = int(m.group(5))
        remarks = m.group(6).strip()

        is_intersection = '进入' in remarks

        if is_intersection:
            m_inter = re.search(r'[由从]\s*([A-Za-z0-9/、，,]+)\s*进入', remarks)
            inter_name = m_inter.group(1) if m_inter else ""
            inter_name = inter_name.replace('、', '/').replace('，', '/').replace(',', '/')
            ident = f"{rwy_id} {inter_name}" if inter_name else rwy_id

            for rwy in airport.runways:
                parent = next(
                    (q for q in rwy.qfus
                     if q.ident == rwy_id and not q.is_intersection),
                    None)
                if parent:
                    new_qfu = QFU(
                        ident=ident,
                        tora=tora, toda=toda, asda=asda, lda=lda,
                        slope=parent.slope,
                        threshold_elevation=parent.threshold_elevation,
                        glide_slope=parent.glide_slope,
                        is_intersection=True,
                    )
                    # 交叉起飞点继承父QFU的磁方位(用于geometry计算)
                    new_qfu.parent_magnetic_heading = parent.magnetic_heading
                    rwy.qfus.append(new_qfu)
                    break
        else:
            for rwy in airport.runways:
                for qfu in rwy.qfus:
                    if qfu.ident == rwy_id and not qfu.is_intersection:
                        qfu.tora = tora
                        qfu.toda = toda
                        qfu.asda = asda
                        qfu.lda = lda
                        break
                else:
                    continue
                break


# ── AD 2.10 障碍物 ────────────────────────

def _parse_ad210(airport: Airport, text: str):
    """解析障碍物数据 — 以序号(3位数字独立行)为锚点"""
    m_section = re.search(r'AD 2\.10.*?(?=AD 2\.11)', text, re.DOTALL)
    if not m_section:
        return
    section = m_section.group()
    lines = section.split('\n')

    _NOISE_KW = [
        '障碍物标志', '障碍物位置', '障碍物名称', 'Obstacle position',
        'Obstacle ID', 'BRG(', 'Designation',
        'marking', 'Flight procedure', 'path area',
        'Lighting Type', '& Colour', '& Remarks',
        '/(Height)', '类型及颜色', '标高或', '影响的飞行程序',
        '1 2 3 4 5 6', '半径 15', '© CAAC', '中国民航', '湖南航空',
        '订购单位', 'NAIP', 'AD 2-', '起飞航径区/备注',
        '或编号', 'Obstacle ID', 'BRG(degree)',
    ]

    def _is_noise(s: str) -> bool:
        if any(kw in s for kw in _NOISE_KW):
            return True
        # 纯英文表头行
        if re.match(r'^(Obstacle|MAG\b|Designation|BRG)', s):
            return True
        # 单纯的控制信息碎片
        if s in ('碍物', '控制障碍物'):
            return True
        return False

    # 第1步: 找到所有序号行
    seq_lines = []  # (line_index, seq_number)
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        m_seq = re.match(r'^(\d{3})\s*$', stripped)
        if m_seq:
            seq_lines.append((i, int(m_seq.group(1))))
            continue
        m_seq2 = re.match(r'^(\d{3})\s{3,}', stripped)
        if m_seq2:
            seq_lines.append((i, int(m_seq2.group(1))))

    # 第2步: 对每个序号, 解析数据
    for si, (seq_idx, seq_num) in enumerate(seq_lines):
        prev_seq_idx = seq_lines[si - 1][0] if si > 0 else max(0, seq_idx - 15)
        next_seq_idx = seq_lines[si + 1][0] if si + 1 < len(seq_lines) else min(len(lines), seq_idx + 8)

        # 区分标准格式和坐标格式:
        # 坐标格式: seq之后紧跟 "NNN/NNNNN" 独立行
        # 标准格式: bearing/distance在seq之前的数据行中
        bearing = 0
        distance = 0
        elev = 0.0
        coord = ""
        is_coord_format = False

        # 检查seq之后是否有独立的 bearing/distance 行
        for j in range(seq_idx + 1, min(seq_idx + 3, next_seq_idx)):
            ln = lines[j].strip()
            m_standalone = re.match(r'^(\d{1,3})\s*/\s*(\d+)\s*$', ln)
            if m_standalone:
                bearing = int(m_standalone.group(1))
                distance = int(m_standalone.group(2))
                is_coord_format = True
                break

        if is_coord_format:
            # 坐标格式: 标高和坐标在seq之前
            # 典型: "山  E1094600  1411 监视引导..."
            for j in range(seq_idx - 1, prev_seq_idx, -1):
                ln = lines[j].strip()
                if not ln or _is_noise(ln):
                    continue
                m_e_coord = re.search(r'[EW](\d{6,7})\s+([\d.]+)', ln)
                if m_e_coord:
                    elev = float(m_e_coord.group(2))
                    break
            # 提取坐标
            for j in range(prev_seq_idx + 1, seq_idx + 1):
                ln = lines[j].strip()
                m_n = re.search(r'([NS]\d{5,6})', ln)
                m_e = re.search(r'([EW]\d{6,7})', ln)
                if m_n:
                    coord = m_n.group(1)
                if m_e:
                    coord = (coord + " " + m_e.group(1)).strip() if coord else m_e.group(1)
        else:
            # 标准格式: 在seq之前找 "类型 bearing/distance elevation" 行
            for j in range(seq_idx - 1, prev_seq_idx, -1):
                ln = lines[j].strip()
                if not ln or _is_noise(ln):
                    continue
                # 清除RWY编号格式避免误匹配
                ln_clean = re.sub(r'RWY\d{2}(?:/\d{2})*', 'RWY__', ln)
                m_pos = re.search(r'(?<!\d)(\d{1,3})\s*/\s*(\d{2,})', ln_clean)
                if m_pos:
                    bearing = int(m_pos.group(1))
                    distance = int(m_pos.group(2))
                    # 标高: bearing/distance之后的数字
                    after = ln_clean[m_pos.end():]
                    m_elev = re.search(r'([\d.]+)', after)
                    if m_elev:
                        elev = float(m_elev.group(1))
                    break

        if bearing == 0 and distance == 0:
            continue

        # 名称: 向前搜索, 跳过噪声/坐标/数据行
        name = ""
        _CTRL_KW = ['起飞航径区', 'GP INOP', 'RNP APCH',
                     '目视盘旋', '进近控制', '扇区控制',
                     'MLT', 'NYB', '重要障碍物']
        search_back_from = seq_idx - 1
        for j in range(search_back_from, prev_seq_idx, -1):
            prev = lines[j].strip()
            if not prev or _is_noise(prev):
                continue
            # 跳过坐标行
            if re.match(r'^[NSEW]\d{5,}', prev):
                continue
            # 跳过包含bearing/distance的数据行
            prev_clean = re.sub(r'RWY\d{2}(?:/\d{2})*', 'RWY__', prev)
            if re.search(r'\d{1,3}\s*/\s*\d{2,}', prev_clean):
                continue
            # 跳过包含 E坐标+标高 的行
            if re.search(r'[EW]\d{6,7}\s+\d', prev):
                continue
            # 含控制信息关键字的行: 尝试提取关键字之前的名称部分
            has_ctrl = False
            for kw in _CTRL_KW:
                if kw in prev:
                    has_ctrl = True
                    break
            if has_ctrl:
                # 尝试提取控制关键字之前的中文名
                parts = re.split(
                    r'\s{2,}|(?=(?:起飞航径|GP INOP|RNP APCH|目视盘旋|进近控制|扇区控制|MLT|NYB|重要障碍物))',
                    prev
                )
                candidate = parts[0].strip() if parts else ""
                # 去掉开头的RWY编号
                candidate = re.sub(r'^RWY\d{2}(?:/\d{2})*\s*', '', candidate).strip()
                if candidate and not _is_noise(candidate) and len(candidate) >= 2:
                    name = candidate
                    break
                # 没有有效名称, 继续向上找
                continue
            # 跳过 "Obstacle" 相关英文表头
            if prev.startswith('Obstacle') or prev.startswith('MAG'):
                continue
            # 这应该是名称行 (包括纯类型词如 "塔台"、"山")
            name = prev.strip()
            break

        # 控制障碍物说明
        ctrl_parts = []
        for j in range(prev_seq_idx + 1, min(next_seq_idx, seq_idx + 3)):
            ln = lines[j].strip()
            if not ln:
                continue
            for kw in ['起飞航径区', '控制障碍物', '扇区控制', 'GP INOP',
                        'RNP APCH', '目视盘旋']:
                if kw in ln:
                    ctrl_parts.append(ln)
                    break
        ctrl = ' '.join(ctrl_parts)
        ctrl = re.sub(r'\s{2,}', ' ', ctrl).strip()

        obs = Obstacle(
            seq=seq_num,
            name=name,
            bearing=bearing,
            distance=distance,
            coordinate=coord,
            elevation_m=elev,
            remark_control=ctrl,
        )
        airport.obstacles.append(obs)
