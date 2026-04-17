"""数据模型 — Airport / Runway / QFU / Obstacle"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Obstacle:
    """AD 2.10 障碍物"""
    seq: int                    # 序号(细则表中的行号, 1-based)
    name: str                   # 障碍物名称
    bearing: int                # 磁方位(度), 整数
    distance: int               # 距离(米), 整数
    coordinate: str = ""        # 经纬度字符串(不参与计算)
    elevation_m: float = 0.0    # 海拔高度(米)
    remark_control: str = ""    # 控制障碍物及涉及航段说明
    note: str = ""              # 备注


@dataclass
class ObstacleResult:
    """某个QFU方向下, 对单个障碍物的分析结果"""
    obstacle: Obstacle
    dist_from_end: int = 0      # S列: 距离跑道末端(米)
    ht_above_end: float = 0.0   # T列: 相对跑道末端高(米)
    is_obstacle: bool = False   # K列: 是否为控制障碍物
    is_shielded: bool = False   # 人工勾选"被遮蔽"
    comment_label: str = ""     # TXT Obstacle Comments, 如 "6 A1-1"
    obs_last_update: str = ""    # 障碍物LastUpdate, 默认用airport级别
    o_val: float = 0.0          # O列: 沿离场路径距离(用于遮蔽计算)
    p_val: float = 0.0          # P列: 垂直离场路径距离(用于遮蔽计算)
    txt_elevation: float = 0.0  # TXT Elevation: ap.elevation + round(HT*M_TO_FT)/M_TO_FT


@dataclass
class QFU:
    """一个起飞/着陆方向(含交叉起飞点)"""
    ident: str                  # 04, 22, 05L, 23R, 22 B10, 05L E3 等
    asda: int = 0
    lda: int = 0
    toda: int = 0
    tora: int = 0
    takeoff_shift: str = ""
    slope: float = 0.0          # 坡度(%), 上坡正下坡负
    threshold_elevation: float = 0.0  # 入口标高(米)
    magnetic_heading: int = 0   # 磁方位(度), per-QFU from AD 2.12
    glide_slope: Optional[float] = None  # 有ILS时-3, 否则None
    ga_method_flag: int = 1     # 0=有ILS, 1=无
    approach_slope: Optional[float] = None  # GAMethodFlag=0时2.5
    increment_ga_height: Optional[float] = None  # GAMethodFlag=0时457.2

    # 离场转弯角(人工填入): 左偏负, 右偏正, 直飞0
    departure_turn_angle: float = 0.0

    # 坐标偏移参数(人工填入, 多跑道时需要):
    departure_x_offset: float = 0.0     # E4: 离地端x轴位移(m)
    rotation_angle: float = 0.0         # F4: x轴正方向旋转角度(度), 交叉跑道用
    arp_offset: float = 0.0             # G4: 机场基准点相对跑道中心位移(m)
    lateral_offset: float = 0.0         # E6: 跑道中心沿y轴位移(m)

    # 障碍物分析结果
    obstacle_results: list[ObstacleResult] = field(default_factory=list)

    # 日期
    last_update: str = ""       # YYYYMMDD
    entry_last_update: str = ""

    # 是否为交叉起飞点
    is_intersection: bool = False

    @property
    def clearway(self) -> int:
        """净空道 = TODA - TORA"""
        return self.toda - self.tora

    @property
    def stopway(self) -> int:
        """停止道 = ASDA - TORA"""
        return self.asda - self.tora

    @property
    def txt_ident(self) -> str:
        """TXT中的Ident格式: 带L/R的无空格, 不带的有空格"""
        if not self.is_intersection:
            return self.ident
        parts = self.ident.split(" ", 1)
        if len(parts) != 2:
            return self.ident
        rwy, intersection = parts
        # 如果跑道号以L/R/C结尾, 不加空格
        if rwy and rwy[-1] in ("L", "R", "C"):
            return rwy + intersection
        return self.ident


@dataclass
class Runway:
    """一条物理跑道"""
    magnetic_heading: int = 0   # 较小端磁方位
    magnetic_heading_date: str = ""  # 磁方位测定日期
    strength: str = ""          # PCN
    max_length: int = 0         # 跑道长度(米)
    width: int = 0              # 宽度(米)
    shoulder: str = ""          # 道肩
    last_update: str = ""       # YYYYMMDD
    qfus: list[QFU] = field(default_factory=list)
    comments: str = ""

    @property
    def has_ils(self) -> bool:
        """该跑道是否有ILS(任一主方向有GlideSlope)"""
        return any(q.glide_slope is not None for q in self.qfus)

    @property
    def main_qfus(self) -> list[QFU]:
        """主方向QFU(非交叉)"""
        return [q for q in self.qfus if not q.is_intersection]

    @property
    def intersection_qfus(self) -> list[QFU]:
        """交叉起飞点QFU"""
        return [q for q in self.qfus if q.is_intersection]


@dataclass
class Airport:
    """机场"""
    icao: str = ""              # ZHHH
    name: str = ""              # TIANHE
    city: str = ""              # WUHAN
    iata: str = ""              # WUH
    elevation: float = 0.0      # 机场标高(米)
    magnetic_variation: str = "" # 045300W
    last_update: str = ""       # YYYYMMDD
    runways: list[Runway] = field(default_factory=list)
    obstacles: list[Obstacle] = field(default_factory=list)  # AD 2.10 全部障碍物
    obstacle_last_update: str = ""  # AD 2.10 页脚日期
    reference_runway_idx: int = 0   # 主跑道索引(D3用此跑道长度)

    @property
    def all_qfus(self) -> list[QFU]:
        """全部QFU(含交叉起飞点)"""
        result = []
        for rwy in self.runways:
            result.extend(rwy.qfus)
        return result
