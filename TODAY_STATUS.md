# 2026-07-23 工作状态记录

## 当前阶段

已经完成小梅沙冷站运行工况识别，并新增第一阶段“仅依靠冷站数据估算集中供冷可调潜力”的计算模块。

这一版属于快速估算模型：暂不耦合建筑热惯性和管网动态，只根据冷站侧的运行工况、系统冷负荷、总功率、蓄冰剩余量和蓄冰变化量估算可响应能力。

## 已完成模块

1. 冷站工况识别
   - 输入文件: `data/小梅沙.xlsx`
   - 规则文件: `src/district_cooling/operation/mode_rules.py`
   - 配置文件: `src/district_cooling/operation/inputs/station_operation_mode_config.json`
   - 输出目录: `data/processed/operation_mode_identification`

2. 冷站侧可调潜力估算
   - 计算模块: `src/district_cooling/operation/flexibility_potential.py`
   - 工具脚本: `tools/estimate_station_flexibility_potential.py`
   - 可视化脚本: `tools/visualize_station_flexibility_potential.py`
   - 配置文件: `src/district_cooling/operation/inputs/station_flexibility_config.json`
   - 输出目录: `data/processed/station_flexibility_potential`

## 当前工况规则

正式保留的工况为:

- 异常
- 制冰
- 释冰
- 释冰+基载
- 释冰+基载+双工况
- 基载
- 基载+双工况

不再单独设置:

- 双工况
- 释冰+双工况

## 可调潜力估算口径

- `cooling_load_kw`: 当前系统冷负荷, 来自冷站数据。
- `power_kw`: 当前冷站总功率, 来自冷站数据。
- `ice_inventory`: 蓄冰剩余量, 按 RT-h 库存理解。
- 换算关系: `1 RT-h = 3.517 kWh`。
- 蓄冰释冷功率:
  - `Q_ice_kw = - ice_delta_per_step * 3.517 / step_h`
  - 当前数据步长 `step_h = 0.25 h`
  - 正值表示释冰, 负值表示制冰。

可调机制:

- 制冰工况: 可调潜力主要来自停止或降低制冰功率。
- 基载、基载+双工况: 可调潜力主要来自使用蓄冰替代部分机械制冷。
- 释冰+基载、释冰+基载+双工况: 可调潜力来自蓄冰槽剩余可增加释冷功率。
- 释冰: 主冷机未运行时, 站侧可削减空间较小。

## 最新可调潜力结果

- 平均当前冷负荷: 7960.8 kW
- 平均当前总功率: 2568.9 kW
- 平均可削减功率: 953.0 kW
- 最大可削减功率: 1339.4 kW
- 平均可响应时长: 1.9 h
- 平均反弹功率: 613.0 kW
- 可响应点数: 441
- 谨慎响应点数: 205
- 不建议响应点数: 50

## 关键输出文件

工况识别:

- `data/processed/operation_mode_identification/station_operation_modes_timeseries.csv`
- `data/processed/operation_mode_identification/station_operation_modes_summary.csv`
- `data/processed/operation_mode_identification/station_operation_mode_criteria.csv`
- `data/processed/operation_mode_identification/station_operation_modes_visual_summary.png`
- `data/processed/operation_mode_identification/station_operation_modes_visualization.html`

可调潜力:

- `data/processed/station_flexibility_potential/station_flexibility_timeseries.csv`
- `data/processed/station_flexibility_potential/station_flexibility_summary.csv`
- `data/processed/station_flexibility_potential/station_flexibility_overall.csv`
- `data/processed/station_flexibility_potential/station_flexibility.xlsx`
- `data/processed/station_flexibility_potential/station_flexibility_report.md`
- `data/processed/station_flexibility_potential/station_flexibility_visual_summary.png`

## 下一步建议

下一步可以围绕“仅靠冷站数据估算可调潜力”继续完善:

- 将可削减功率、响应时长、反弹功率整理成项目报告中的正式指标定义。
- 对不同工况分别给出可调潜力解释和适用边界。
- 加入电价时段后, 把“是否建议响应”从能力判断扩展到经济性判断。
- 后续再进入第二阶段: 建立区域侧快速量化数据集, 把冷站、管网、建筑负荷联动起来。
