"""实验辅助类材料工具：实验方案生成 / 实验记录模板 / 危险试剂安全提示。

内置 4 套规范实验模板（standard/synthesis/characterization/electrochem）与常见
危险化学品库，全部离线可用；旧键 hydrothermal/solgel/calcination 作为 synthesis
别名保留。
"""

from __future__ import annotations

from typing import Any, Dict, List

from tools.registry import registry, tool_result


# ─────────────────────────────────────────────────────────────
# ① 实验方案生成器（内置 4 套模板）
# ─────────────────────────────────────────────────────────────
# 规范四键（设置 experiment.template / GET /api/experiment/templates 用这四个）：
#   standard / synthesis / characterization / electrochem
# 旧键 hydrothermal / solgel / calcination 作为 synthesis 的别名保留，
# 收到仍能工作（见 _TEMPLATE_ALIASES），向后兼容既有调用与历史记录。
EXPERIMENT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "standard": {
        "name": "标准实验记录",
        "applicable": "通用实验方案编排，适用于各类材料/化学/物理实验的标准化流程与记录",
        "reagents_placeholder": "按实验目的选择试剂（前驱体/溶剂/催化剂/对照样），注明纯度、规格与批号",
        "equipment": "通用玻璃器皿、分析天平、磁力搅拌器、烘箱、通风橱、pH 计、数据采集装置",
        "steps": [
            "明确研究目标与待验证假设，列出变量与对照（空白/基准样）",
            "按计量关系计算并称取试剂，记录试剂批号与环境温湿度",
            "配制体系并按既定流程操作，实时记录关键现象与参数",
            "设置平行样（≥3）以评估重复性",
            "后处理（分离/洗涤/干燥）并标记样品编号",
            "按表征/测试计划采集数据，原始数据归档索引",
            "整理结果、与假设对照，给出结论与下一步",
        ],
        "safety": "通用实验安全：穿实验服、戴护目镜与手套，通风橱内操作挥发性/腐蚀性试剂；废弃物分类收集",
        "notes": "建议固定记录模板（日期/操作人/变量/异常），保证可追溯与可复现",
    },
    "synthesis": {
        "name": "材料合成",
        "applicable": "纳米材料、氧化物粉体、薄膜等合成路线（归并水热、溶胶-凝胶、共沉淀、煅烧等合成家族）",
        "reagents_placeholder": "金属盐前驱体、溶剂（水/乙醇/异丙醇）、沉淀剂或螯合剂（NaOH/尿素/乙酰丙酮）、去离子水",
        "equipment": "高压反应釜、磁力搅拌器、离心机、烘箱、马弗炉/管式炉、研磨工具",
        "steps": [
            "按目标计量比称取前驱体，溶于溶剂搅拌至完全均匀",
            "按需滴加沉淀剂/螯合剂并调 pH，搅拌形成均匀前驱体（溶胶/沉淀/混合液）",
            "转移至反应容器：水热路线装入反应釜（填充度≤80%），或直接加热反应",
            "按设定温度/时间/气氛恒温反应（如 120–200 ℃ 数小时）",
            "自然冷却后离心/过滤收集产物，去离子水与乙醇交替洗涤去除残留离子",
            "干燥（60–100 ℃）后按需煅烧/退火（如 400–700 ℃，升温 2–5 ℃/min）",
            "研磨收集，标记样品编号待表征",
        ],
        "safety": "高压反应釜须检查内衬、控填充度、冷却后再开釜；金属醇盐遇水放热、溶剂易燃；高温炉具佩戴隔热手套",
        "notes": "温度/时间/前驱体浓度/pH 是主要调控参数，建议正交实验；煅烧升温速率影响晶粒尺寸与相纯度",
    },
    "characterization": {
        "name": "性能表征",
        "applicable": "XRD/SEM/TEM/BET/XPS/电化学等结构与性能表征测试方案编排与记录",
        "reagents_placeholder": "待测样品、标准参比样、测试载体/导电胶带、电解液（电化学表征用）",
        "equipment": "XRD 衍射仪、SEM/TEM、BET 比表面分析仪、XPS、电化学工作站",
        "steps": [
            "整理待测样品清单，注明批次、制备方法与外观",
            "结构表征：XRD（2θ 范围/步长）确定物相与结晶度",
            "形貌表征：SEM/TEM（加速电压/倍数）观察尺寸与形貌",
            "成分/表面：BET 比表面、XPS 元素价态分析（按需）",
            "性能表征：电化学（CV/EIS/充放电）或其它物性测试，记录测试参数",
            "原始数据按编号归档，注明处理软件与版本",
            "对比标准谱图/文献，归纳结构-性能关系",
        ],
        "safety": "XRD/XPS 为电离辐射源，关门/联锁后开机；SEM/TEM 高压电与真空环境，按规程操作；电解液腐蚀性注意防护",
        "notes": "测试参数（加速电压、扫描速率、2θ 步长）须记录以保证可复现；优先用标准样校准仪器",
    },
    "electrochem": {
        "name": "电化学测试",
        "applicable": "CV/LSV/EIS/恒流充放电、超级电容器、电池电极评价",
        "reagents_placeholder": "活性材料、导电剂（乙炔黑）、粘结剂（PVDF/Nafion）、溶剂（NMP/乙醇）、电解液、参比/对电极",
        "equipment": "电化学工作站、三电极电解池/扣式电池组装件、玻碳电极/集流体、烘箱、手套箱（可选）",
        "steps": [
            "电极制备：活性材料:导电剂:粘结剂 = 8:1:1（质量比），研磨混合",
            "滴涂/涂覆于集流体，60–80 ℃ 真空干燥 12 h",
            "组装三电极体系（工作电极/参比/对电极）或扣式电池",
            "注入电解液，静置 2–4 h 至浸润平衡",
            "CV 测试：设置电位窗口与扫描速率（5–100 mV/s）",
            "EIS 测试：频率 0.01 Hz–100 kHz，振幅 5–10 mV",
            "恒流充放电/循环稳定性测试，记录比容量与库仑效率",
        ],
        "safety": "电解液（如 LiPF6 系）对水氧敏感且具腐蚀性：手套箱/密封操作，避免接触皮肤；高电位测试防触电",
        "notes": "电极负载量、电解液匹配、测试参数需注明，便于结果复现",
    },
}

# 旧模板键 → 规范键 的别名映射（向后兼容既有调用与历史记录）。
_TEMPLATE_ALIASES: Dict[str, str] = {
    "hydrothermal": "synthesis",
    "solgel": "synthesis",
    "calcination": "synthesis",
}


def _resolve_template(template: str) -> str:
    """把可能的别名键解析为规范键；无法识别时原样返回（交给调用方报错）。"""
    return _TEMPLATE_ALIASES.get(template, template)


def experiment_protocol_tool(
    goal: str,
    template: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """根据研究目标生成实验方案（内置标准/合成/表征/电化学模板）。

    Args:
        goal: 研究目标描述（如"制备 TiO2 纳米颗粒"）。
        template: 模板名：standard / synthesis / characterization / electrochem；
            旧键 hydrothermal / solgel / calcination 作为 synthesis 的别名仍被接受。

    Returns:
        完整实验方案（试剂/仪器/步骤/安全/备注）。
    """
    tpl_key = _resolve_template(template)
    tpl = EXPERIMENT_TEMPLATES.get(tpl_key)
    if tpl is None:
        opts = " / ".join(list(EXPERIMENT_TEMPLATES) + list(_TEMPLATE_ALIASES))
        return {
            "error": f"未知模板：{template}（可选：{opts}）",
            "available_templates": list(EXPERIMENT_TEMPLATES.keys()),
        }
    return {
        "goal": goal,
        "template": tpl["name"],
        "template_key": tpl_key,
        "applicable": tpl["applicable"],
        "reagents": tpl["reagents_placeholder"],
        "equipment": tpl["equipment"],
        "steps": tpl["steps"],
        "safety": tpl["safety"],
        "notes": tpl["notes"],
        "tips": "请根据实际目标细化试剂用量（可用溶液配制/摩尔质量工具计算）与具体参数",
    }


EXPERIMENT_PROTOCOL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "生成实验方案：标准记录/材料合成/性能表征/电化学测试模板。",
    "examples": [{"goal": "制备 TiO2 纳米颗粒", "template": "synthesis"}],
    "properties": {
        "goal": {"type": "string", "description": "研究目标，如 制备 TiO2 纳米颗粒 / 合成 NiCo2O4 并测试超级电容性能"},
        "template": {"type": "string",
                     "enum": list(EXPERIMENT_TEMPLATES.keys()) + list(_TEMPLATE_ALIASES.keys()),
                     "description": "实验模板：standard 标准记录 / synthesis 材料合成 / characterization 性能表征 / electrochem 电化学测试（旧键 hydrothermal/solgel/calcination 等同 synthesis）"},
    },
    "required": ["goal", "template"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ② 实验记录模板生成
# ─────────────────────────────────────────────────────────────
def lab_notebook_template_tool(
    scenario: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """生成标准化 Markdown 实验记录模板。

    Args:
        scenario: "synthesis"（材料合成）| "characterization"（表征测试）。

    Returns:
        含 markdown 字段的完整模板。
    """
    if scenario == "synthesis":
        md = """# 实验记录：材料合成

- **日期**：____-__-__
- **操作人**：
- **实验目的**：

## 1. 原料与用量
| 试剂 | 分子式 | 纯度/规格 | 用量 | 摩尔数 | 来源/批号 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 2. 合成步骤
1. （前驱体配制）
2. （反应条件：温度/时间/气氛）
3. （后处理：洗涤/干燥/煅烧）

## 3. 仪器与参数
- 设备：  
- 关键参数：

## 4. 产物信息
- 外观：  
- 质量：____ g，产率：____ %
- 表征计划：XRD / SEM / TEM / BET / XPS …

## 5. 安全与异常
- 安全提示执行情况：
- 异常现象与处理：

## 6. 备注
"""
    elif scenario == "characterization":
        md = """# 实验记录：表征测试

- **日期**：____-__-__
- **操作人**：
- **样品编号**：

## 1. 样品信息
- 样品名称/批次：
- 制备方法摘要：
- 外观与质量：

## 2. 测试条件
| 表征手段 | 仪器型号 | 测试参数 | 样品制备 |
|---|---|---|---|
| XRD |  | 2θ范围/步长 |  |
| SEM/TEM |  | 加速电压/倍数 |  |
| 光谱/电化学 |  | 参数 |  |

## 3. 原始数据索引
- 数据文件路径/编号：
- 处理软件与版本：

## 4. 结果要点
1. （峰位/形貌/性能数值）

## 5. 结论与下一步
"""
    else:
        return {"error": f"未知场景：{scenario}（可选 synthesis / characterization）"}
    return {"scenario": scenario, "markdown": md, "format": "Markdown"}


LAB_NOTEBOOK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "生成标准化 Markdown 实验记录模板（合成/表征两类场景）。",
    "examples": [{"scenario": "synthesis"}],
    "properties": {
        "scenario": {"type": "string", "enum": ["synthesis", "characterization"],
                     "description": "记录场景：synthesis 材料合成 / characterization 表征测试"},
    },
    "required": ["scenario"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# ③ 危险试剂安全提示（内置常见危险品库）
# ─────────────────────────────────────────────────────────────
CHEMICAL_SAFETY_DB: Dict[str, Dict[str, Any]] = {
    "氢氟酸": {"cas": "7664-39-3", "hazards": ["强腐蚀性，可穿透皮肤损伤骨骼", "吸入蒸气严重刺激呼吸道"],
              "protection": ["专用 HF 手套 + 防护服 + 面罩", "在通风橱操作", "备好葡萄糖酸钙凝胶"],
              "emergency": ["皮肤接触：立即大量清水冲洗 15 min 以上，涂葡萄糖酸钙凝胶并就医",
                            "溅入眼睛：持续冲洗并立即就医", "吸入：转移至新鲜空气处，立即就医"]},
    "浓硫酸": {"cas": "7664-93-9", "hazards": ["强脱水性与强腐蚀性", "遇水剧烈放热喷溅"],
              "protection": ["耐酸手套、护目镜、围裙", "稀释时必须酸入水（缓慢搅拌）"],
              "emergency": ["皮肤接触：干布擦去后大量清水冲洗 15 min", "溅入眼睛：持续冲洗 15 min 就医",
                            "衣物着火：不可用水扑救，用灭火器/沙土"]},
    "浓硝酸": {"cas": "7697-37-2", "hazards": ["强氧化性腐蚀性，与有机物混合可自燃", "挥发出 NOx 有毒黄烟"],
              "protection": ["耐酸手套护目镜，通风橱操作", "远离还原剂/有机物"],
              "emergency": ["皮肤接触：清水冲洗 15 min 就医", "吸入 NOx：转移新鲜空气处，吸氧就医"]},
    "氢氧化钠": {"cas": "1310-73-2", "hazards": ["强碱腐蚀性，溶解放热"],
               "protection": ["防碱手套护目镜", "溶解时缓慢搅拌散热"],
               "emergency": ["皮肤接触：大量清水冲洗 15 min", "溅入眼睛：持续冲洗 15 min 立即就医"]},
    "过氧化氢(浓)": {"cas": "7722-84-1", "hazards": ["强氧化剂，高浓度遇有机物可燃爆", "见光分解"],
                    "protection": ["远离热源/有机物/还原剂", "避光阴凉保存，专用容器"],
                    "emergency": ["皮肤接触：清水冲洗", "泄漏：稀释后收集，禁混有机物"]},
    "氢氟醚/四氢呋喃": {"cas": "109-99-9", "hazards": ["易燃液体，蒸气与空气形成爆炸混合物", "易形成过氧化物"],
                       "protection": ["远离明火静电", "使用前检测过氧化物", "通风橱操作"],
                       "emergency": ["泄漏：切断火源，沙土围堵", "火灾：干粉/CO2 灭火器，禁用水"]},
    "正己烷": {"cas": "110-54-3", "hazards": ["高度易燃", "蒸气吸入有麻醉作用"],
              "protection": ["远离火源，密封保存", "通风操作"],
              "emergency": ["泄漏：切断火源，吸附材料收集", "火灾：泡沫/干粉灭火器"]},
    "硝酸银": {"cas": "7761-88-8", "hazards": ["氧化性，腐蚀皮肤，遇光分解变黑"],
              "protection": ["避光保存", "接触后皮肤会染色", "佩戴手套"],
              "emergency": ["皮肤接触：冲洗", "误食：立即就医"]},
    "铅盐(如硝酸铅)": {"cas": "10099-74-8", "hazards": ["重金属毒性，蓄积性危害"],
                       "protection": ["手套+口罩，避免粉尘吸入", "操作后彻底洗手"],
                       "emergency": ["误食：立即就医", "吸入粉尘：转移新鲜空气处就医"]},
    "镉盐(如硫酸镉)": {"cas": "10124-36-4", "hazards": ["致癌物，肝肾毒性"],
                       "protection": ["避免吸入粉尘，手套口罩", "废弃物按危废处理"],
                       "emergency": ["误食/吸入：立即就医"]},
    "液氮": {"cas": "7727-37-9", "hazards": ["极低温冻伤", "密闭容器内蒸发超压"],
             "protection": ["低温手套+护目镜", "通风良好处使用"],
             "emergency": ["冻伤：勿揉搓，温水缓慢复温后就医"]},
    "氩气/氮气(高压)": {"cas": "7440-37-1", "hazards": ["高压钢瓶爆炸风险", "密闭空间窒息"],
                       "protection": ["钢瓶固定，搬运用推车", "减压阀检查", "通风"],
                       "emergency": ["泄漏：通风，人员撤离", "窒息：移至新鲜空气处急救"]},
}


def chemical_safety_tool(
    reagent: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """查询危险试剂的防护要求与应急处理（内置常见危险品库）。

    Args:
        reagent: 试剂名称或化学式（如 氢氟酸 / 浓硫酸 / HF）。

    Returns:
        危害、防护、应急处理与 CAS 号；未收录时给出通用提示。
    """
    # 精确匹配 + 模糊匹配
    direct = CHEMICAL_SAFETY_DB.get(reagent)
    if direct is None:
        for name, info in CHEMICAL_SAFETY_DB.items():
            if reagent.lower() in name.lower() or name.lower() in reagent.lower():
                direct = info
                reagent = name
                break
    if direct is None:
        return {
            "reagent": reagent,
            "found": False,
            "message": "该试剂未收录于内置危险品库，请查阅 SDS（安全数据表）。以下为通用建议：",
            "protection_general": ["佩戴实验室护目镜与手套", "在通风橱内操作", "远离火源与不相容物质"],
            "suggested_sources": ["试剂瓶 SDS 标签", "供应商官网 SDS 数据库"],
        }
    return {"reagent": reagent, "found": True, "cas": direct["cas"],
            "hazards": direct["hazards"], "protection": direct["protection"],
            "emergency": direct["emergency"]}


CHEMICAL_SAFETY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "查询危险试剂防护要求与应急处理（内置常见危险化学品库）。",
    "examples": [{"reagent": "氢氟酸"}],
    "properties": {
        "reagent": {"type": "string", "description": "试剂名称或化学式，如 氢氟酸 / 浓硫酸 / 硝酸银"},
    },
    "required": ["reagent"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────
def _check_experiment_available() -> bool:
    return True


registry.register(
    name="experiment_protocol",
    toolset="matlens_material",
    schema=EXPERIMENT_PROTOCOL_SCHEMA,
    handler=lambda args, **kw: tool_result(experiment_protocol_tool(goal=args.get("goal", ""), template=args.get("template", ""))),
    check_fn=_check_experiment_available,
    description="生成实验方案：标准记录/材料合成/性能表征/电化学测试 4 套模板，输出试剂仪器步骤与安全提示",
    emoji="🧫",
)

registry.register(
    name="lab_notebook_template",
    toolset="matlens_material",
    schema=LAB_NOTEBOOK_SCHEMA,
    handler=lambda args, **kw: tool_result(lab_notebook_template_tool(scenario=args.get("scenario", "synthesis"))),
    check_fn=_check_experiment_available,
    description="生成标准化 Markdown 实验记录模板（材料合成/表征测试两类场景）",
    emoji="📒",
)

registry.register(
    name="chemical_safety",
    toolset="matlens_material",
    schema=CHEMICAL_SAFETY_SCHEMA,
    handler=lambda args, **kw: tool_result(chemical_safety_tool(reagent=args.get("reagent", ""))),
    check_fn=_check_experiment_available,
    description="查询危险试剂防护要求与应急处理（内置常见危险化学品库，如氢氟酸/浓硫酸/硝酸银）",
    emoji="⚠️",
)
