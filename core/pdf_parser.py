"""AIP PDF 解析 — 提取 AD 2.1/2.2/2.10/2.12/2.13 数据

针对中国民航国内航空资料汇编(NAIP)的标准PDF格式。
使用pdfplumber提取表格和文本。
"""
from __future__ import annotations
import re
from typing import Optional
from core.models import Airport, Runway, QFU, Obstacle
from templates.constants import FT_TO_M, APPROACH_SLOPE, INCREMENT_GA_HEIGHT


def parse_aip_pdf(filepath: str) -> Airport:
    """
    解析AIP PDF, 返回Airport对象.
    提取 AD 2.1 (ICAO/IATA/名称), AD 2.2 (标高/磁差),
    AD 2.12 (跑道物理特征), AD 2.13 (申报距离), AD 2.10 (障碍物).
    """
    import pdfplumber

    airport = Airport()
    all_text = ""
    all_tables: list[list[list]] = []

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_text += text + "\n"
            for table in (page.extract_tables() or []):
                all_tables.append(table)

    _parse_header(airport, all_text)
    _parse_ad22(airport, all_tables)
    _parse_ad212(airport, all_tables)
    _parse_ad213(airport, all_tables)
    _parse_ad210(airport, all_tables)

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
    # 注: ga_method_flag / approach_slope / increment_ga_height 由用户在GUI中手动设置
    for rwy in airport.runways:
        if rwy.has_ils:
            for qfu in rwy.qfus:
                if qfu.glide_slope is None:
                    qfu.glide_slope = -3

    # 根据入口标高差计算有效坡度(对多段坡度场景更准确, 保证同跑道两端坡度互为相反数)
    for rwy in airport.runways:
        mains = rwy.main_qfus
        if len(mains) == 2 and rwy.max_length > 0:
            t0 = mains[0].threshold_elevation
            t1 = mains[1].threshold_elevation
            if t0 > 0 and t1 > 0:
                eff_slope = round((t1 - t0) / rwy.max_length * 100, 2)
                mains[0].slope = eff_slope
                mains[1].slope = -eff_slope
                # 同步交叉起飞点坡度
                for iq in rwy.intersection_qfus:
                    parent_ident = iq.ident.split()[0] if " " in iq.ident else iq.ident
                    if parent_ident == mains[0].ident:
                        iq.slope = mains[0].slope
                    elif parent_ident == mains[1].ident:
                        iq.slope = mains[1].slope

    return airport


# ── AD 2.1 机场代码和名称 ──────────────────

def _parse_header(airport: Airport, text: str):
    """从首页文本提取ICAO/IATA/城市/名称
    格式: ZSWX/WUX-无锡/硕放WUXI/Shuofang
    """
    # ICAO/IATA
    m = re.search(r'\b([A-Z]{4})/([A-Z]{3})\b', text)
    if m:
        airport.icao = m.group(1)
        airport.iata = m.group(2)

    # 英文城市/名称: 中文字符后出现 "WUXI/Shuofang"
    m = re.search(
        r'[\u4e00-\u9fff]\s*([A-Z][A-Za-z]+)\s*/\s*([A-Za-z]+)',
        text[:3000]
    )
    if m:
        airport.city = m.group(1).upper()
        airport.name = m.group(2).upper()


# ── AD 2.2 机场地理位置和管理资料 ──────────

def _parse_ad22(airport: Airport, tables: list):
    """解析标高、磁差"""
    for table in tables:
        for row in table:
            if not row or len(row) < 3:
                continue
            row_text = _row_text(row)

            # 标高: "5.1 m(17ft)/30.6℃..." or "34.5 m(114ft)/..."
            # 仅匹配含"机场标高"的行, 且只取首次匹配
            if airport.elevation == 0 and ('机场标高' in row_text or
                ('ELEV' in row_text.upper() and 'AD ELEV' not in row_text.upper()
                 and '入口' not in row_text)):
                data = _last_nonempty(row)
                # 优先用ft值(ft*0.3048更精确)
                m_ft = re.search(r'(\d+)\s*ft', data)
                if m_ft:
                    airport.elevation = round(int(m_ft.group(1)) * FT_TO_M, 4)
                else:
                    m_m = re.search(r'([\d.]+)\s*m', data)
                    if m_m:
                        airport.elevation = float(m_m.group(1))

            # 磁差: "4°53′W(2024)/-" or "5°13′W/-"
            if '磁差' in row_text or ('VAR' in row_text.upper() and
                                       'change' in row_text.lower()):
                data = _last_nonempty(row)
                m = re.search(r'(\d+)[°度]\s*(\d+)?[′\'′]?\s*([WE])', data)
                if m:
                    deg = int(m.group(1))
                    mins = int(m.group(2)) if m.group(2) else 0
                    d = m.group(3)
                    airport.magnetic_variation = f"{deg:02d}{mins:02d}00{d}"


# ── AD 2.12 跑道物理特征 ──────────────────

def _parse_ad212(airport: Airport, tables: list):
    """解析跑道物理数据, 建立Runway和QFU对象.
    注意: AD 2.12 表可能跨页拆分为多个物理表, 需要合并后再配对.
    """
    # 第1步: 从所有AD 2.12表中收集QFU行
    all_qfu_rows: list[tuple[QFU, list, dict]] = []  # (qfu, row, cols)
    shoulder_notes: list[str] = []  # 备注中的道肩信息

    for table in tables:
        if not table or len(table) < 3:
            continue
        header_text = _row_text(table[0])

        # 识别AD 2.12跑道表: 含"跑道号码"+("磁方位"|"长宽")
        if not ('跑道' in header_text and
                ('磁方位' in header_text or 'MAG' in header_text.upper() or
                 '长宽' in header_text or 'Dimensions' in header_text)):
            continue
        # 排除AD 2.13(含TORA)和灯光表
        if 'TORA' in header_text or '进近灯' in header_text:
            continue

        # 检测列位置(按表头内容, 兼容7列和8列格式)
        cols = {}
        for i, cell in enumerate(table[0]):
            ct = _cs(cell).lower()
            if '跑道号码' in ct or ('rwy' in ct and 'design' in ct):
                cols['rwy'] = i
            elif '磁方位' in ct or 'mag' in ct or '真方位' in ct:
                cols['bearing'] = i
            elif '长宽' in ct or 'dimensions' in ct:
                cols['dims'] = i
            elif ('强度' in ct or 'strength' in ct) and '跑道' in _row_text(table[0]).lower():
                cols['pcn'] = i
            elif '入口标高' in ct or 'thr elevation' in ct:
                cols['thr_elev'] = i
            elif '坡度' in ct or 'slope' in ct:
                cols['slope'] = i

        if 'rwy' not in cols:
            continue

        # 收集QFU和对应行数据
        found_data = False
        for row in table:
            rwy_id = _cs(row[cols['rwy']])

            # 遇到第二个表头段(如SWY/CWY部分)时停止
            if ('跑道' in rwy_id or 'RWY' in rwy_id.upper()) and found_data:
                # 继续扫描备注行(道肩等信息)
                for rest_row in table[table.index(row):]:
                    rest_text = _row_text(rest_row)
                    if '道肩' in rest_text:
                        shoulder_notes.append(rest_text)
                break

            if not re.match(r'\d{2}[LRC]?$', rwy_id):
                continue

            found_data = True
            qfu = QFU(ident=rwy_id)

            # 入口标高 — 优先用ft值(ft*0.3048更精确)
            if 'thr_elev' in cols:
                thr_text = _cs(row[cols['thr_elev']])
                m_ft = re.search(r'THR\s*[\d.]+\s*m\s*/\s*(\d+)\s*ft', thr_text)
                if m_ft:
                    qfu.threshold_elevation = round(int(m_ft.group(1)) * FT_TO_M, 4)
                else:
                    m_m = re.search(r'THR\s*([\d.]+)\s*m', thr_text)
                    if m_m:
                        qfu.threshold_elevation = float(m_m.group(1))
                # ILS: TDZ存在 = 精密进近
                if 'TDZ' in thr_text:
                    qfu.glide_slope = -3

            # 磁方位(per-QFU)
            if 'bearing' in cols:
                brg_text = _cs(row[cols['bearing']])
                m_brg = re.search(r'(\d+)\s*°?\s*MAG', brg_text)
                if m_brg:
                    qfu.magnetic_heading = int(m_brg.group(1))

            # 坡度(取第一段)
            if 'slope' in cols:
                slope_text = _cs(row[cols['slope']])
                m = re.search(r'(-?[\d.]+)%', slope_text)
                if m:
                    qfu.slope = float(m.group(1))

            all_qfu_rows.append((qfu, row, cols))

        # 扫描备注行(可能在数据行之后)
        if not found_data:
            for row in table:
                rest_text = _row_text(row)
                if '道肩' in rest_text:
                    shoulder_notes.append(rest_text)

    # 第2步: 按对组建Runway(连续两个QFU构成一条物理跑道)
    i = 0
    while i < len(all_qfu_rows):
        q1, r1, c1 = all_qfu_rows[i]
        rwy = Runway()
        rwy.qfus.append(q1)
        _fill_runway_from_row(rwy, r1, c1)

        if i + 1 < len(all_qfu_rows):
            q2, r2, c2 = all_qfu_rows[i + 1]
            rwy.qfus.append(q2)
            i += 2
        else:
            i += 1

        # 跑道磁方位取较小的QFU方位
        headings = [q.magnetic_heading for q in rwy.qfus if q.magnetic_heading]
        if headings:
            rwy.magnetic_heading = min(headings)

        airport.runways.append(rwy)

    # 第3步: 从备注中提取道肩信息(支持多跑道组)
    for note in shoulder_notes:
        # 按跑道组分割: 找所有 "XX/YY：..." 段落
        pairs = re.findall(
            r'(\d{2}[LRC]?(?:/\d{2}[LRC]?)*)\s*[：:]\s*[^；;]*?道肩[^；;]*?(?:各|宽)\s*([\d.]+)\s*m',
            note
        )
        for rwy_group, shoulder_val in pairs:
            rwy_ids = re.findall(r'\d{2}[LRC]?', rwy_group)
            for rwy in airport.runways:
                rwy_idents = {q.ident for q in rwy.qfus}
                if any(rid in rwy_idents for rid in rwy_ids):
                    rwy.shoulder = shoulder_val
                    break
        # 如果没有按组匹配到, 尝试整体匹配(兼容旧格式)
        if not pairs:
            m = re.search(r'(?:各|宽)\s*([\d.]+)\s*m', note)
            if not m:
                continue
            shoulder_val = m.group(1)
            label_part = note.split('：')[0] if '：' in note else note.split(':')[0]
            rwy_match = re.findall(r'\d{2}[LRC]?', label_part)
            if not rwy_match:
                continue
            for rwy in airport.runways:
                rwy_idents = {q.ident for q in rwy.qfus}
                if any(rid in rwy_idents for rid in rwy_match):
                    rwy.shoulder = shoulder_val
                    break


def _fill_runway_from_row(rwy: Runway, row: list, cols: dict):
    """从AD 2.12数据行提取跑道级信息(仅在跑道尚无该数据时填充)"""
    # 尺寸: "3400×45"
    if 'dims' in cols and rwy.max_length == 0:
        dims = _cs(row[cols['dims']])
        m = re.search(r'(\d+)\s*[×xX]\s*(\d+)', dims)
        if m:
            rwy.max_length = int(m.group(1))
            rwy.width = int(m.group(2))

    # PCN: "PCR 1130/R/A/W/T\n沥青/-"
    if 'pcn' in cols and not rwy.strength:
        pcn = _cs(row[cols['pcn']])
        m = re.search(r'(?:PCR|PCN)\s*(\d+/[A-Z]/[A-Z]/[A-Z]/[A-Z])', pcn)
        if m:
            rwy.strength = m.group(1)


# ── AD 2.13 申报距离 ──────────────────────

def _parse_ad213(airport: Airport, tables: list):
    """解析申报距离, 填充QFU和检测交叉起飞点"""
    for table in tables:
        if not table or len(table) < 3:
            continue
        header_text = _row_text(table[0])
        if 'TORA' not in header_text:
            continue

        # 列位置
        cols = {}
        for i, cell in enumerate(table[0]):
            ct = _cs(cell).upper()
            if 'TORA' in ct:
                cols['tora'] = i
            elif 'TODA' in ct:
                cols['toda'] = i
            elif 'ASDA' in ct:
                cols['asda'] = i
            elif 'LDA' in ct:
                cols['lda'] = i
            elif '跑道' in _cs(cell) or 'RWY' in ct:
                cols['rwy'] = i
            elif '备注' in _cs(cell) or 'REMARK' in ct:
                cols['remarks'] = i

        if 'tora' not in cols:
            continue

        for row in table:
            rwy_id = _cs(row[cols.get('rwy', 0)])
            if not re.match(r'\d{2}[LRC]?$', rwy_id):
                continue

            tora = _parse_int(row, cols.get('tora'))
            toda = _parse_int(row, cols.get('toda'))
            asda = _parse_int(row, cols.get('asda'))
            lda_cell = _cs(row[cols['lda']]) if 'lda' in cols else ""
            lda = _parse_int(row, cols.get('lda')) \
                if lda_cell not in ('-', '—', '') else 0

            remarks = _cs(row[cols['remarks']]) if 'remarks' in cols else ""

            # 交叉起飞点: 备注含"由/从XXX进入"
            is_intersection = '进入' in remarks

            if is_intersection:
                m = re.search(r'[由从]\s*([A-Za-z0-9/、，,]+)\s*进入', remarks)
                inter_name = m.group(1) if m else ""
                # 将中文标点替换为斜杠
                inter_name = inter_name.replace('、', '/').replace('，', '/').replace(',', '/')
                ident = f"{rwy_id} {inter_name}" if inter_name else rwy_id

                # 附加到对应跑道
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
                            magnetic_heading=parent.magnetic_heading,
                            glide_slope=parent.glide_slope,
                            is_intersection=True,
                        )
                        rwy.qfus.append(new_qfu)
                        break
            else:
                # 填充已有QFU的距离
                for rwy in airport.runways:
                    for qfu in rwy.qfus:
                        if qfu.ident == rwy_id and not qfu.is_intersection:
                            # 安全检查: 如已有距离且TORA不同, 可能是未识别的交叉起飞点
                            if qfu.tora > 0 and tora != qfu.tora:
                                full_row_text = _row_text(row)
                                if '进入' in full_row_text:
                                    m_inter = re.search(
                                        r'[由从]\s*([A-Za-z0-9/、，,]+)\s*进入',
                                        full_row_text)
                                    inter_name = m_inter.group(1) if m_inter else ""
                                    inter_name = inter_name.replace(
                                        '、', '/').replace('，', '/').replace(',', '/')
                                    ident = f"{rwy_id} {inter_name}" if inter_name else rwy_id
                                    new_qfu = QFU(
                                        ident=ident,
                                        tora=tora, toda=toda, asda=asda, lda=lda,
                                        slope=qfu.slope,
                                        threshold_elevation=qfu.threshold_elevation,
                                        magnetic_heading=qfu.magnetic_heading,
                                        glide_slope=qfu.glide_slope,
                                        is_intersection=True,
                                    )
                                    rwy.qfus.append(new_qfu)
                                # 无"进入"关键字且TORA不同时不覆盖, 避免误修改
                            else:
                                qfu.tora = tora
                                qfu.toda = toda
                                qfu.asda = asda
                                qfu.lda = lda
                            break
                    else:
                        continue
                    break


# ── AD 2.10 障碍物 ────────────────────────

def _parse_ad210(airport: Airport, tables: list):
    """解析障碍物表(可能跨多页, 每页表头重复)"""
    for table in tables:
        if not table or len(table) < 3:
            continue
        # 放宽列数限制: 允许4-10列(兼容PDF提取的列数差异)
        ncols = len(table[0])
        if ncols < 4 or ncols > 10:
            continue
        first_rows = " ".join(
            _row_text(table[i]) for i in range(min(3, len(table))))
        if '障碍物' not in first_rows:
            continue
        if '磁方位' not in first_rows and 'BRG' not in first_rows.upper():
            continue

        for row in table:
            if not row or len(row) < 4:
                continue

            # 动态查找包含 "磁方位/距离" 格式的列 (如 "002/2634")
            m_pos = None
            pos_col_idx = -1
            for ci in range(len(row)):
                candidate = _cs(row[ci])
                m = re.search(r'(\d{1,3})\s*/\s*(\d+)', candidate)
                if m:
                    m_pos = m
                    pos_col_idx = ci
                    break

            if not m_pos:
                continue

            bearing = int(m_pos.group(1))
            distance = int(m_pos.group(2))

            # 名称: 位置列之前所有列合并
            name_cell = _cs(row[0])
            if pos_col_idx > 1:
                name_cell = ' '.join(
                    _cs(row[c]) for c in range(pos_col_idx) if c < len(row))

            # 序号: 名称单元格末尾独立的1-3位数字行
            actual_seq = 0
            cell_lines = name_cell.strip().split('\n')
            for line in reversed(cell_lines):
                line = line.strip()
                if re.match(r'^\d{1,3}$', line):
                    actual_seq = int(line)
                    break

            # 名称: 去掉末尾序号行, 拼接
            name_parts = []
            for line in cell_lines:
                if re.match(r'^\d{1,3}$', line.strip()):
                    break
                name_parts.append(line.strip())
            name = ''.join(name_parts)

            # 标高(米): 位置列之后的下一列
            elev = 0.0
            elev_col = pos_col_idx + 1
            if elev_col < len(row):
                elev_cell = _cs(row[elev_col])
                m_elev = re.search(r'[\d.]+', elev_cell)
                if m_elev:
                    elev = float(m_elev.group())

            # 控制障碍物/航段说明: 最后一列(若在标高列之后还有)
            ctrl = ""
            if len(row) > elev_col + 1:
                ctrl = _cs(row[-1])

            obs = Obstacle(
                seq=actual_seq,
                name=name,
                bearing=bearing,
                distance=distance,
                elevation_m=elev,
                remark_control=ctrl,
            )
            airport.obstacles.append(obs)


# ── 工具函数 ──────────────────────────────

def _cs(cell) -> str:
    """Cell to string, None safe"""
    return str(cell).strip() if cell is not None else ""


def _row_text(row: list) -> str:
    """拼接行所有单元格为文本"""
    if not row:
        return ""
    return " ".join(_cs(c) for c in row)


def _last_nonempty(row: list) -> str:
    """返回行中最后一个非空单元格"""
    for cell in reversed(row):
        s = _cs(cell)
        if s:
            return s
    return ""


def _parse_int(row: list, col: Optional[int]) -> int:
    """从单元格提取整数"""
    if col is None or col >= len(row):
        return 0
    s = _cs(row[col])
    m = re.search(r'\d+', s)
    return int(m.group()) if m else 0
