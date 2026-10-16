"""材料领域技能包入口：导入即注册全部 16 个工具。

工具分类：
- 计算辅助：molar_mass 摩尔质量 / solution_prep 溶液配制 / tauc_bandgap 带隙
            / energy_convert 能量单位换算 / battery_capacity 电池理论比容量
            / thermo_gibbs 热力学判据 / lever_rule 相图杠杆定律
- 实验辅助：experiment_protocol 实验方案 / lab_notebook_template 记录模板 / chemical_safety 危险试剂
- 数据处理：xrd_preprocess XRD 预处理 / xrd_dspacing 晶面间距换算 / data_normalize 数据归一化
- 可视化：experiment_plot 实验数据绘图
- 写作辅助：citation_format 文献格式化 / experiment_writing 实验润色
"""

from matlens_kit.tools import computation  # noqa: F401
from matlens_kit.tools import data_processing  # noqa: F401
from matlens_kit.tools import electrochem  # noqa: F401
from matlens_kit.tools import experiment  # noqa: F401
from matlens_kit.tools import il_viscosity  # noqa: F401
from matlens_kit.tools import plotting  # noqa: F401
from matlens_kit.tools import thermo  # noqa: F401
from matlens_kit.tools import writing  # noqa: F401

__all__ = ["computation", "data_processing", "electrochem", "experiment",
           "il_viscosity", "plotting", "thermo", "writing"]
MATERIAL_TOOLS = [
    "molar_mass", "solution_prep", "tauc_bandgap", "energy_convert",
    "battery_capacity", "thermo_gibbs", "lever_rule",
    "experiment_protocol", "lab_notebook_template", "chemical_safety",
    "xrd_preprocess", "xrd_dspacing", "data_normalize",
    "experiment_plot",
    "citation_format", "experiment_writing",
    "il_viscosity_predict",
]
