# 区域集中供冷 RC 模型 Python 项目

本项目用于搭建区域集中供冷系统的 RC 动态模型。当前已经完成基础系统框架和建筑负荷模块的校准流程，后续可以继续加入冷站设备、蓄冰、泵阀、控制策略和优化调度模块。

## 当前模块

- `plant`：冷站参数模块。当前提供冷站供水温度和冷水机组基础性能参数，暂不做设备调度。
- `network`：供回水管网 RC 模型。考虑管网水体热容、管网热阻、土壤温度和水流携带热量。
- `load`：建筑负荷 RC 模型。当前为两节点模型：室内空气节点和室内物品/墙体热质节点。
- `calibration`：建筑 RC 参数识别模块。支持固定参数模型和基于实测数据的参数估计模型。
- `flexibility`：可调潜力量化指标模块。用于根据基线功率、响应功率和反弹功率曲线计算正式评价指标。
- `results`：结果输出模块。负责输出 CSV 和 PNG 图。
- `system`：系统耦合仿真模块。连接冷站、供水管网、建筑和回水管网。

## 建筑 RC 模型

建筑负荷模型位于：

```text
src/district_cooling/load/building_rc.py
```

当前空气节点方程：

```text
C_indoor * dT_indoor/dt =
    (T_outdoor - T_indoor) / R_outwall
    + (T_m - T_indoor) / R_m
    + Q_internal
    - Q_ac
```

当前热质节点方程：

```text
C_m * dT_m/dt =
    (T_indoor - T_m) / R_m
    + Q_solar
    + Q_thermal_mass
```

其中：

- `T_indoor`：室内空气温度。
- `T_outdoor`：室外空气温度。
- `T_m`：室内物品/墙体等热质温度。
- `R_outwall`：室外空气到室内空气的等效外墙热阻。
- `R_m`：室内空气与室内热质之间的等效换热热阻。
- `C_indoor`：室内空气等效热容。
- `C_m`：室内物品、墙体等热质的等效热容。
- `Q_internal`：直接进入室内空气节点的内热源。
- `Q_solar`：进入热质节点的太阳辐照得热。
- `Q_thermal_mass`：进入热质节点的虚拟热源。
- `Q_ac`：空调制冷量。

注意：当前 `Q_ac` 使用实测水流量、供水温度和回水温度计算：

```text
Q_ac = m_dot * cp * (T_return - T_supply)
```

空调制冷量不再使用任何修正系数。

## 参数输入文件

建筑基础参数：

```text
src/district_cooling/load/inputs/building_basic.json
```

三组实测数据运行配置：

```text
src/district_cooling/load/inputs/measurements/wzs_building_run_config.json
src/district_cooling/load/inputs/measurements/wzs1_building_validation_run_config.json
src/district_cooling/load/inputs/measurements/wzs2_building_validation_run_config.json
```

三组参数估计配置：

```text
src/district_cooling/load/inputs/calibration/building_rc_structured_prior_dynamic_calibration_config.json
src/district_cooling/load/inputs/calibration/wzs1_building_structured_prior_dynamic_calibration_config.json
src/district_cooling/load/inputs/calibration/wzs2_building_structured_prior_dynamic_calibration_config.json
```

建筑类型 RC 先验库：

```text
src/district_cooling/load/inputs/building_type_rc_priors.json
```

这个文件保存了商业购物、办公建筑、低层住宅、中层住宅和高层住宅的 2R2C 参数范围。当前项目按“办公建筑”引用该先验。

注意：先验数据中的 `U_z` 和 `U_1` 从量纲和模型形式看是热导 `W/K`，而本项目方程使用热阻 `K/W`。因此在代码中会按下式换算：

```text
R_outwall = 1 / U_z
R_m = 1 / U_1
C_m = C_1
C_indoor = Cin
```

由于这些先验来自不同体量的建筑，当前只作为物理合理性参考和越界提示，暂不作为硬边界强行截断优化结果。

三组参数估计后仿真配置：

```text
src/district_cooling/load/inputs/measurements/wzs_building_run_with_structured_prior_dynamic_fitted_parameters_config.json
src/district_cooling/load/inputs/measurements/wzs1_building_run_with_auto_identified_rc_parameters_config.json
src/district_cooling/load/inputs/measurements/wzs2_building_run_with_auto_identified_rc_parameters_config.json
```

## 参数识别算法

参数识别模块位于：

```text
src/district_cooling/calibration/
```

当前识别参数为：

```text
R_outwall
R_m
C_indoor
C_m
```

算法特点：

- 使用结构化物理参数生成 R/C 参考值，但最终直接拟合 R/C 本身。
- 使用软先验约束，避免参数偏离物理尺度过远。
- 使用温度误差和温度变化斜率误差共同构成目标函数。
- 区分空调开启段和空调关闭段，使算法能学习“空调开启时快速降温、空调关闭时自然缓慢升温”的动态差异。
- 不拟合空调制冷量修正系数。

## 数据量和周期判断

参数识别前会先评估数据是否适合拟合。

当前判断逻辑：

- 如果数据时长过短，或覆盖周期数不足，会提示建议优先使用固定参数模型。
- 周期不再简单假设为 24 小时。
- 周期检测同时使用三种方法：
  - 不等间隔时间序列的频谱扫描。
  - 自相关分析。
  - 峰谷间隔检测。
- 训练集切分时会保证训练段至少覆盖一个检测到的完整周期。

这样可以避免用户输入非 15 分钟间隔数据时，算法仍错误依赖固定采样间隔。

## 常用运行命令

运行系统耦合基础仿真：

```powershell
python .\main.py
```

运行 WZS 固定参数模型：

```powershell
python .\examples\run_building_with_measurements.py src/district_cooling/load/inputs/measurements/wzs_building_run_config.json
```

运行 WZS1 固定参数模型：

```powershell
python .\examples\run_building_with_measurements.py src/district_cooling/load/inputs/measurements/wzs1_building_validation_run_config.json
```

运行 WZS2 固定参数模型：

```powershell
python .\examples\run_building_with_measurements.py src/district_cooling/load/inputs/measurements/wzs2_building_validation_run_config.json
```

运行 WZS 参数识别：

```powershell
python .\examples\calibrate_building_rc.py src/district_cooling/load/inputs/calibration/building_rc_structured_prior_dynamic_calibration_config.json
```

运行 WZS1 参数识别：

```powershell
python .\examples\calibrate_building_rc.py src/district_cooling/load/inputs/calibration/wzs1_building_structured_prior_dynamic_calibration_config.json
```

运行 WZS2 参数识别：

```powershell
python .\examples\calibrate_building_rc.py src/district_cooling/load/inputs/calibration/wzs2_building_structured_prior_dynamic_calibration_config.json
```

运行测试：

```powershell
python -m unittest discover -s tests
```

## 当前三组数据结果

最近一次固定参数模型与参数估计模型对比表：

```text
run_cache/three_dataset_fixed_vs_identified_summary.csv
```

最近一次三组识别 R/C 参数表：

```text
run_cache/three_dataset_identified_rc_parameters.csv
```

## 缓存与输出

`run_cache/` 用于保存最近阶段的运行结果、CSV 和 PNG 图。它属于过程输出目录，不是模型源代码。

Python 自动生成的 `__pycache__/` 和 `.pyc` 文件不需要保留，可以随时删除。

## WZS 实测太阳辐照

WZS 校准数据现在使用 `data/XIHE_Meteorological_Data_1784520445.csv` 中的实测太阳辐照。运行配置位于：

```text
src/district_cooling/load/inputs/measurements/wzs_building_run_config.json
src/district_cooling/load/inputs/measurements/wzs_building_run_with_structured_prior_dynamic_fitted_parameters_config.json
```

配置中的 `solar_measurement` 会读取 `日期`、`时间`、`法向直接辐射W/m^2`、`散射辐射W/m^2`，用线性插值对齐到 WZS 的 15 分钟时间戳，并用 `equivalent_solar_gain_area_m2` 将总辐照强度换算为模型使用的太阳得热功率。

## 建筑热容与室内热质热阻

当前建筑侧把外墙、地板和室内其他物品统一作为 `T_m` 热质节点的一部分，因此 `C_m` 和 `R_m` 的计算需要使用同一套物理边界：

```text
A_floor = 建筑地上总面积
A_wall = 建筑数量 * 单栋建筑外轮廓周长 * 楼层数 * 层高

R_m = 1 / (h_m * (A_floor + A_wall))

C_m =
    C_object_per_floor_area * A_floor
    + rho_floor * c_floor * delta_floor * A_floor
    + rho_wall * c_wall * delta_wall * A_wall
```

其中 `C_object_per_floor_area * A_floor` 表示室内其他物品的等效热容，目前先作为单位楼面面积定值输入；后续可以进一步由人员、设备、家具或使用功能计算得到。地板和外墙热容分别由材料密度、比热、厚度和面积计算得到。

## 办公建筑内墙体积估算

内墙体积估算模块位于：

```text
src/district_cooling/load/office_geometry.py
```

用户后期只需要输入建筑单层总面积、层高、层数以及办公室平均尺寸，即可估算办公建筑内墙体积。当前平均办公室尺寸取：

```text
office_width = 4.95 m
office_depth = 5.70 m
office_area = 28.215 m2
```

核心公式为：

```text
N_office = A_floor / A_office

W_plan = sqrt(A_floor * aspect_ratio)
D_plan = sqrt(A_floor / aspect_ratio)

L_inner = A_floor / office_width
        + A_floor / office_depth
        - (W_plan + D_plan)

A_inner_wall = L_inner * floor_height
V_inner_wall = A_inner_wall * wall_thickness
```

其中 `L_inner` 已经扣除了外轮廓墙，表示相邻办公室之间共享隔墙的估算长度。`layout_complexity_factor` 可用于后期修正走廊、设备间、非规则隔断等造成的内墙增减。

当前项目的输入位置为：

```text
src/district_cooling/load/inputs/building_basic.json
```

对应配置段为：

```json
"interior_wall_estimation": {
  "office_module": {
    "width_m": 4.95,
    "depth_m": 5.70
  },
  "wall_thickness_m": 0.1,
  "plan_aspect_ratio": 1.0,
  "layout_complexity_factor": 1.0
}
```

## 冷站工况识别模块

冷站工况识别模块位于：

```text
src/district_cooling/operation/
```

其中：

```text
station_data.py  读取 data/小梅沙.xlsx 中的最终版冷站实测数据
mode_rules.py    计算工况判据指标，并给每个时间点打工况标签
inputs/station_operation_mode_config.json  配置冷机角色和工况判定阈值
inputs/station_equipment_roles.md          记录原设计与当前实际设备角色
```

当前冷站设备角色说明：

```text
原设计: 1 台机载/基载冷水机组 + 3 台双工况冷水机组 + 蓄冰槽
实际状态: 2 台机载/常规制冷冷水机组 + 1 台双工况冷水机组 + 1 台故障双工况冷水机组 + 蓄冰槽
当前配置: CH_01、CH_04 作为机载/常规制冷冷机，CH_02 作为双工况冷机，CH_03 暂不参与主工况判别
```

运行入口为：

```powershell
python .\tools\identify_station_operation_modes.py --clean
```

默认输入文件：

```text
data/小梅沙.xlsx
```

默认输出目录：

```text
data/processed/operation_mode_identification/
```

主要输出文件：

```text
station_operation_modes_timeseries.csv  每个时间点的工况判定和判据变量
station_operation_modes_summary.csv     各工况持续时间、平均冷负荷、平均功率等汇总
station_operation_modes_daily.csv       每天各工况出现次数
station_operation_modes.xlsx            汇总到一个 Excel 文件中的结果
station_operation_modes_report.md       文字版工况判据和汇总说明
```

生成工况可视化：

```powershell
python .\tools\visualize_station_operation_modes.py
```

可视化输出：

```text
station_operation_modes_visual_summary.png   工况识别总览图
station_operation_modes_visualization.html   可直接打开的 HTML 总览页
```

运行聚类验证分析：

```powershell
python .\tools\cluster_station_operation_modes.py
```

聚类输出：

```text
data/processed/operation_mode_clustering/operation_mode_cluster_report.md
data/processed/operation_mode_clustering/rule_mode_vs_cluster_crosstab.csv
data/processed/operation_mode_clustering/operation_mode_cluster_pca.png
data/processed/operation_mode_clustering/cluster_boundary_points.csv
```

聚类只用于校验规则工况、发现边界点和识别子工况，不替代规则工况标签。

计算冷机制冷量：

```powershell
python .\tools\calculate_station_water_side_capacity.py
```

当前使用 `src/district_cooling/operation/inputs/chiller_water_side_capacity_config.json` 中的冷机-水泵映射、额定流量与 COP。由于 `CH_01` 基载冷水机组功率列明显偏低，当前采用混合计算：

```text
CH_01: Q = rho * cp * flow_m3h / 3600 * (T_chw_in - T_chw_out)
CH_02: Q = P_motor * COP，制冰 COP=4.11，空调制冷 COP=5.83
CH_04: Q = P_motor * COP，当前按双工况改造后空调制冷 COP=5.83
```

当前暂不使用 `CH_01__power_kw` 参与制冷量计算。

冷水机组额定参考参数存放在：

```text
src/district_cooling/operation/inputs/chiller_reference_parameters.json
```

目前采用的主要参考值为：

```text
双工况冷水机组 空调工况: 5415 kW, 928.4 kW, COP 5.83
双工况冷水机组 蓄冰工况: 4220 kW, 1026 kW, COP 4.11
基载离心式冷水机组 空调工况: 3868 kW, 675.5 kW, COP 5.73
基载离心式冷水机组 名义工况: 3868 kW, 570.9 kW, COP 6.78
一期空调工况总制冷量: 20113 kW
```

水侧冷量结果会同时输出 `capacity_over_reference_ratio`，用于检查由温差和水泵流量估算出的冷量是否超过单机额定能力。

当前第一版规则使用的主要判据变量包括：

```text
冷负荷率 = SYS_TOTAL.cooling_load / 20113
机载/基载冷水机组运行台数 = 配置中 base_chiller_ids 对应 CH_xx.status > 0.5 的数量
双工况冷水机组运行台数 = 配置中 dual_mode_chiller_ids 对应 CH_xx.status > 0.5 的数量
冷却塔运行台数 = CT_xx.power_kw > 1 的数量
水泵运行台数 = PUMP_xx.power_kw > 1 的数量
蓄冰量变化 = 当前 ICE_01.inventory_rt - 上一时刻 ICE_01.inventory_rt
单位冷量功率 = SYS_TOTAL.power_kw / SYS_TOTAL.cooling_load
```

第一版可解释工况包括：

```text
异常
基载
基载+双工况
制冰
释冰
释冰+基载
释冰+基载+双工况
```

## 可调潜力量化模块

正式可调潜力量化模块位于：

```text
src/district_cooling/flexibility/
```

该模块保留项目方案中的通用指标体系，输入为三类功率曲线：

```text
P_base(t)      常规运行状态下的系统功率
P_dr(t)        削峰响应时段内的系统功率
P_reb(t)       响应结束后的反弹阶段系统功率
```

当前实现的主要指标为：

```text
A  = max(P_base - P_dr)                         最大削减功率
TA = t_Amax - t_drst                            到达最大削减功率时间
a  = integral(P_base - P_dr)dt / (t_drend-t_drst) 平均削减功率
B  = max(P_reb - P_base)                        最大反弹功率
Tb = t_rebend - t_drend                         反弹时间
b  = integral(P_reb - P_base)dt / Tb             平均反弹功率
ΔX = X_joint - X_single                         绝对协同效应
ΔX% = ΔX / X_single * 100%                      相对协同效应
```

其中综合可调能力暂保留为可配置函数：

```text
F = f(P_base, P_dr, P_reb)
```

代码默认先使用保守净值：

```text
F = A - B
```

注意：`operation/flexibility_potential.py` 中的冷站侧可调潜力估算仍然保留。它用于从冷站工况、蓄冰剩余量和冷机 COP 快速估算站侧可调边界；`flexibility/metrics.py` 则用于后续全系统仿真后，对基线、响应和反弹曲线进行统一评价。

> A Method for Rapid Quantification of the Flexibility Potential of District Cooling Systems

