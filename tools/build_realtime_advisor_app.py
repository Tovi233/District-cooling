from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "data" / "processed" / "station_flexibility_potential" / "station_flexibility_timeseries.csv"
NORMALIZED_INPUT_PATH = PROJECT_ROOT / "data" / "processed" / "station_device_run_normalized.csv"
FLEXIBILITY_CONFIG_PATH = PROJECT_ROOT / "src" / "district_cooling" / "operation" / "inputs" / "station_flexibility_config.json"
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "realtime_station_advisor_app.html"

DESIGN_COOLING_CAPACITY_KW = 20113.0
DUAL_ICE_MAKING_CAPACITY_KW = 4220.0
DUAL_AIR_CONDITION_CAPACITY_KW = 5415.0
DUAL_ICE_MAKING_RATED_OUT_TEMP_C = -5.6
DUAL_AIR_CONDITION_OUT_TEMP_C = 6.0
BASE_AIR_CONDITION_CAPACITY_KW = 3868.0
BASE_AIR_CONDITION_COP = 5.73
DUAL_AIR_CONDITION_COP = 5.83
DUAL_ICE_MAKING_RATED_POWER_KW = 1026.0
WATER_HEAT_KW_PER_M3H_C = 1.163
CONTRACT_SUPPLY_TEMP_C = 4.0
BASE_CHILLER_FLOW_M3H = 788.0
DUAL_CHILLER_FLOW_M3H = 1200.0
BASE_CHILLER_PUMP_POWER_KW = 110.0
DUAL_CHILLER_PUMP_POWER_KW = 132.0
RT_TO_KWH = 3.517
STEP_H = 0.25


def main() -> None:
    rows = _load_rows()
    flexibility_config = _load_flexibility_config()
    max_ice_inventory_kwh = flexibility_config.get("max_ice_inventory_kwh")
    if max_ice_inventory_kwh is None:
        max_ice_inventory_kwh = max(row["ice_inventory_kwh"] for row in rows)
    ice_discharge_power_limit_kw = flexibility_config.get("max_ice_discharge_power_kw")
    if ice_discharge_power_limit_kw is None:
        ice_discharge_power_limit_kw = max(row["max_ice_discharge_power_kw"] for row in rows)
    html = HTML_TEMPLATE
    replacements = {
        "__DATA_JSON__": json.dumps(rows, ensure_ascii=False),
        "__MAX_ICE_INVENTORY_KWH__": f"{float(max_ice_inventory_kwh):.6f}",
        "__ICE_DISCHARGE_POWER_LIMIT_KW__": f"{float(ice_discharge_power_limit_kw):.6f}",
        "__DESIGN_COOLING_CAPACITY_KW__": f"{DESIGN_COOLING_CAPACITY_KW:.6f}",
        "__TARGET_RESPONSE_DURATION_H__": f"{float(flexibility_config.get('target_response_duration_h', 2.0)):.6f}",
        "__DUAL_ICE_MAKING_CAPACITY_KW__": f"{DUAL_ICE_MAKING_CAPACITY_KW:.6f}",
        "__DUAL_AIR_CONDITION_CAPACITY_KW__": f"{DUAL_AIR_CONDITION_CAPACITY_KW:.6f}",
        "__DUAL_ICE_MAKING_RATED_OUT_TEMP_C__": f"{DUAL_ICE_MAKING_RATED_OUT_TEMP_C:.6f}",
        "__DUAL_AIR_CONDITION_OUT_TEMP_C__": f"{DUAL_AIR_CONDITION_OUT_TEMP_C:.6f}",
        "__BASE_AIR_CONDITION_CAPACITY_KW__": f"{BASE_AIR_CONDITION_CAPACITY_KW:.6f}",
        "__BASE_AIR_CONDITION_COP__": f"{BASE_AIR_CONDITION_COP:.6f}",
        "__DUAL_AIR_CONDITION_COP__": f"{DUAL_AIR_CONDITION_COP:.6f}",
        "__DUAL_ICE_MAKING_RATED_POWER_KW__": f"{DUAL_ICE_MAKING_RATED_POWER_KW:.6f}",
        "__WATER_HEAT_KW_PER_M3H_C__": f"{WATER_HEAT_KW_PER_M3H_C:.6f}",
        "__CONTRACT_SUPPLY_TEMP_C__": f"{CONTRACT_SUPPLY_TEMP_C:.6f}",
        "__BASE_CHILLER_FLOW_M3H__": f"{BASE_CHILLER_FLOW_M3H:.6f}",
        "__DUAL_CHILLER_FLOW_M3H__": f"{DUAL_CHILLER_FLOW_M3H:.6f}",
        "__BASE_CHILLER_PUMP_POWER_KW__": f"{BASE_CHILLER_PUMP_POWER_KW:.6f}",
        "__DUAL_CHILLER_PUMP_POWER_KW__": f"{DUAL_CHILLER_PUMP_POWER_KW:.6f}",
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(OUTPUT_PATH)


def _load_flexibility_config() -> dict:
    if not FLEXIBILITY_CONFIG_PATH.exists():
        return {}
    return json.loads(FLEXIBILITY_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_rows() -> list[dict]:
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    df["collect_time_iso"] = pd.to_datetime(df["collect_time_iso"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.sort_values("collect_time_iso")
    df = df.merge(_load_chiller_extra_by_time(), on="collect_time_iso", how="left", suffixes=("", "_extra"))

    rows: list[dict] = []
    for _, row in df.iterrows():
        measured_delta = _safe_float(row.get("gap_aware_ice_delta_rt"), _safe_float(row.get("ice_delta_per_step")))
        dual_on = int(_safe_float(row.get("dual_chiller_on_count")))
        dual_out = _safe_float(row.get("dual_min_chw_out_temp_c"), 99.0)
        dual_mode = "ice_making" if dual_on >= 1 and dual_out < 0.0 else "cooling"
        ice_discharge_on = measured_delta < -50.0 and dual_mode != "ice_making"
        effective_delta = _effective_ice_delta(dual_on, dual_out, measured_delta, ice_discharge_on)
        rows.append(
            {
                "collect_time_iso": str(row["collect_time_iso"]),
                "cooling_load_kw": _safe_float(row.get("cooling_load_kw")),
                "flow_m3h": _safe_float(row.get("effective_chiller_flow_m3h"), _safe_float(row.get("flow_m3h"))),
                "measured_flow_m3h": _safe_float(row.get("flow_m3h")),
                "power_kw": _safe_float(row.get("power_kw")),
                "ice_inventory_kwh": _safe_float(row.get("ice_remaining_kwh"), _safe_float(row.get("ice_inventory")) * RT_TO_KWH),
                "total_supply_temp_c": _safe_float_or_none(row.get("total_supply_temp_c")),
                "contract_supply_temp_c": CONTRACT_SUPPLY_TEMP_C,
                "measured_ice_delta_per_step_kwh": measured_delta * RT_TO_KWH,
                "ice_discharge_on": "yes" if ice_discharge_on else "no",
                "ice_delta_per_step_kwh": effective_delta * RT_TO_KWH,
                "min_chiller_setpoint_c": CONTRACT_SUPPLY_TEMP_C,
                "dual_min_chw_out_temp_c": dual_out,
                "dual_chiller_mode": dual_mode,
                "base_chiller_on_count": int(_safe_float(row.get("base_chiller_on_count"))),
                "dual_chiller_on_count": dual_on,
                "base_chiller_power_kw": _safe_float(row.get("base_chiller_power_kw")),
                "dual_chiller_power_kw": _safe_float(row.get("dual_chiller_power_kw"), _safe_float(row.get("dual_chiller_power_kw_extra"))),
                "base_chiller_avg_freq_hz": _safe_float_or_none(row.get("base_chiller_avg_freq_hz")),
                "dual_chiller_avg_freq_hz": _safe_float_or_none(row.get("dual_chiller_avg_freq_hz")),
                "max_ice_discharge_power_kw": _safe_float(row.get("max_available_ice_discharge_kw")),
                "ice_supported_duration_h": _safe_float(row.get("ice_supported_duration_h")),
            }
        )
    return rows


def _load_chiller_extra_by_time() -> pd.DataFrame:
    columns = ["collect_time_iso", "base_chiller_avg_freq_hz", "dual_chiller_avg_freq_hz", "dual_chiller_power_kw"]
    if not NORMALIZED_INPUT_PATH.exists():
        return pd.DataFrame(columns=columns)
    data = pd.read_csv(NORMALIZED_INPUT_PATH, encoding="utf-8-sig")
    if not {"collect_time_iso", "device_id", "freq_hz"}.issubset(data.columns):
        return pd.DataFrame(columns=columns)
    data["collect_time_iso"] = pd.to_datetime(data["collect_time_iso"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    data["freq_hz"] = pd.to_numeric(data["freq_hz"], errors="coerce")
    data.loc[data["freq_hz"] <= 0, "freq_hz"] = pd.NA
    base = data[data["device_id"].isin(["CH_01", "CH_04"])].groupby("collect_time_iso")["freq_hz"].mean()
    dual = data[data["device_id"].isin(["CH_02"])].groupby("collect_time_iso")["freq_hz"].mean()
    dual_power = data[data["device_id"].isin(["CH_02"])].groupby("collect_time_iso")["power_kw"].sum()
    return pd.concat(
        [
            base.rename("base_chiller_avg_freq_hz"),
            dual.rename("dual_chiller_avg_freq_hz"),
            dual_power.rename("dual_chiller_power_kw"),
        ],
        axis=1,
    ).reset_index()[columns]


def _effective_ice_delta(dual_on: int, dual_out_temp_c: float, measured_delta: float, ice_discharge_on: bool) -> float:
    if dual_on >= 1 and dual_out_temp_c < 0.0:
        return _dual_ice_making_power_kw(dual_on, dual_out_temp_c) * STEP_H / RT_TO_KWH
    if not ice_discharge_on:
        return 0.0
    return min(measured_delta, -50.0)


def _dual_ice_making_power_kw(dual_on: int, dual_out_temp_c: float) -> float:
    temp = min(max(dual_out_temp_c, DUAL_ICE_MAKING_RATED_OUT_TEMP_C), 0.0)
    slope = (DUAL_AIR_CONDITION_CAPACITY_KW - DUAL_ICE_MAKING_CAPACITY_KW) / (
        DUAL_AIR_CONDITION_OUT_TEMP_C - DUAL_ICE_MAKING_RATED_OUT_TEMP_C
    )
    return dual_on * (DUAL_ICE_MAKING_CAPACITY_KW + slope * (temp - DUAL_ICE_MAKING_RATED_OUT_TEMP_C))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_float_or_none(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>冷站实时可调能力建议</title>
  <style>
    :root { --bg:#f5f7fb; --panel:#fff; --line:#d8e0ea; --text:#152033; --muted:#64748b; --blue:#174ea6; --green:#2e7d32; --amber:#b7791f; --gray:#6b7280; --red:#d62728; --orange:#ff7f0e; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; }
    .app { min-height:100vh; display:grid; grid-template-columns:480px 1fr; }
    aside { background:#fff; border-right:1px solid var(--line); padding:24px 22px; overflow:auto; }
    main { padding:24px 30px 34px; overflow:auto; }
    h1 { margin:0 0 6px; font-size:26px; }
    h2 { margin:24px 0 12px; font-size:18px; }
    .sub,.note { color:var(--muted); font-size:13px; line-height:1.55; }
    label { display:block; font-size:13px; color:#334155; margin-bottom:5px; }
    input,select { width:100%; height:38px; border:1px solid #cbd5e1; border-radius:6px; padding:0 10px; font-size:14px; background:#fff; }
    input:disabled,select:disabled { background:#f1f5f9; color:#64748b; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .wide { grid-column:1 / -1; }
    .mode-panel,.section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; margin-top:16px; }
    .mode-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }
    .time-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
    .control-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }
    button { height:38px; border:0; border-radius:6px; background:var(--blue); color:#fff; font-size:14px; cursor:pointer; }
    button.secondary { background:#e8eef8; color:var(--blue); }
    button:disabled { background:#e2e8f0; color:#94a3b8; cursor:not-allowed; }
    .summary { display:grid; grid-template-columns:repeat(4,minmax(160px,1fr)); gap:14px; margin-top:18px; }
    .metric { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; min-height:98px; }
    .metric .name { color:var(--muted); font-size:14px; margin-bottom:9px; }
    .metric .value { font-size:28px; font-weight:700; }
    .metric .unit { font-size:13px; color:var(--muted); margin-left:4px; }
    .status { display:inline-flex; align-items:center; height:34px; border-radius:999px; padding:0 14px; font-weight:700; color:#fff; background:var(--gray); }
    .status.ok { background:var(--green); } .status.mid { background:var(--amber); } .status.no { background:var(--gray); }
    .topline { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .bar-row { display:grid; grid-template-columns:145px 1fr 102px; align-items:center; gap:12px; margin:12px 0; font-size:14px; }
    .track { height:18px; background:#eef2f7; border-radius:5px; overflow:hidden; }
    .fill { height:100%; width:0; } .stop { background:var(--orange); } .shift { background:var(--red); } .supply { background:#0891b2; } .rebound { background:#7c3aed; }
    .actions { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    ol,ul { margin:0; padding-left:22px; line-height:1.72; font-size:15px; }
    .operation-summary { font-size:18px; line-height:1.65; }
    @media (max-width:1100px) { .app{grid-template-columns:1fr;} aside{border-right:0;border-bottom:1px solid var(--line);} .summary{grid-template-columns:repeat(2,minmax(160px,1fr));} .actions{grid-template-columns:1fr;} }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <h1>实时运行数据</h1>
    <div class="sub">自动模式下选择时间，其他测点同步到该时刻；手动模式下可以直接输入当前实测值。</div>
    <div class="mode-panel">
      <label>输入模式</label>
      <div class="mode-row"><button id="autoBtn">自动同步</button><button id="manualBtn" class="secondary">手动输入</button></div>
    </div>
    <div class="grid">
      <div class="wide"><label for="timeSelect">数据时间</label><select id="timeSelect"></select></div>
      <div class="wide time-row"><button id="prevTimeBtn" class="secondary">上一时刻</button><button id="nextTimeBtn" class="secondary">下一时刻</button></div>
      <div><label for="cooling_load_kw">当前冷负荷 kW</label><input id="cooling_load_kw" type="number" step="0.01" data-input-field /></div>
      <div><label for="flow_m3h">运行机组冷冻水流量 m3/h（自动）</label><input id="flow_m3h" type="number" step="0.01" disabled /></div>
      <div><label for="power_kw">冷站总功率 kW（自动）</label><input id="power_kw" type="number" step="0.01" disabled /></div>
      <div><label for="total_supply_temp_c">总供水温度 ℃</label><input id="total_supply_temp_c" type="number" step="0.01" data-input-field /></div>
      <div><label for="contract_supply_temp_c">合同供水温度 ℃</label><input id="contract_supply_temp_c" type="number" step="0.01" data-input-field /></div>
      <div><label for="target_response_duration_h">目标响应时长 h</label><input id="target_response_duration_h" type="number" step="0.25" min="0.25" value="__TARGET_RESPONSE_DURATION_H__" data-parameter-field /></div>
      <div><label for="ice_inventory_kwh">蓄冰剩余量 kWh</label><input id="ice_inventory_kwh" type="number" step="0.01" data-input-field /></div>
      <div><label for="measured_ice_delta_per_step_kwh">冰量库存差分 kWh</label><input id="measured_ice_delta_per_step_kwh" type="number" step="0.01" data-input-field /></div>
      <div><label for="ice_discharge_on">当前是否释冰</label><select id="ice_discharge_on" data-input-field><option value="yes">是</option><option value="no">否</option></select></div>
      <div><label for="base_chiller_on_count">基载机组运行台数</label><input id="base_chiller_on_count" type="number" step="1" data-input-field /></div>
      <div><label for="dual_chiller_on_count">双工况机组运行台数</label><input id="dual_chiller_on_count" type="number" step="1" data-input-field /></div>
      <div><label for="dual_chiller_mode">双工况冷水机组工况</label><select id="dual_chiller_mode" data-input-field><option value="cooling">制冷</option><option value="ice_making">制冰</option></select></div>
    </div>
    <h2>运行状态参考</h2>
    <div class="grid">
      <div><label for="operation_mode">当前工况（自动判断）</label><input id="operation_mode" type="text" disabled /></div>
      <div><label for="ice_delta_per_step_kwh">用于计算的单步冰量变化 kWh</label><input id="ice_delta_per_step_kwh" type="number" step="0.01" disabled /></div>
      <div><label for="min_chiller_setpoint_c">供水设定温度 ℃（参考）</label><input id="min_chiller_setpoint_c" type="number" step="0.01" disabled /></div>
      <div><label for="current_ice_discharge_power_kw">当前释冰功率 kW（自动计算）</label><input id="current_ice_discharge_power_kw" type="number" step="0.01" disabled /></div>
      <div><label for="base_chiller_power_kw">基载冷机电功率 kW（自动计算）</label><input id="base_chiller_power_kw" type="number" step="0.01" disabled /></div>
      <div><label for="dual_chiller_power_kw">双工况冷机电功率 kW（自动计算）</label><input id="dual_chiller_power_kw" type="number" step="0.01" disabled /></div>
    </div>
    <div class="control-row"><button id="calcBtn">重新计算</button><button id="latestBtn" class="secondary">跳到最新</button></div>
    <div class="note">工况判断优先级：1 制冰：双工况运行且出水温度低于0℃；2 释冰：当前是否释冰=是；3 其余按基载/双工况运行台数组合判断。蓄冰余量只代表可用能力，不等于当前正在释冰。</div>
  </aside>
  <main>
    <div class="topline"><div><h1>可调能力与实时建议</h1><div class="sub" id="currentTime"></div></div><div id="levelBadge" class="status">--</div></div>
    <div class="section">
      <h2>系统状态观察</h2>
      <div class="summary">
        <div class="metric"><div class="name">系统总电功率</div><span class="value" id="systemPower">--</span><span class="unit">kW</span></div>
        <div class="metric"><div class="name">冷水机组电功率</div><span class="value" id="chillerPower">--</span><span class="unit">kW</span></div>
        <div class="metric"><div class="name">水泵电功率</div><span class="value" id="pumpPower">--</span><span class="unit">kW</span></div>
        <div class="metric"><div class="name">系统总制冷量</div><span class="value" id="systemCooling">--</span><span class="unit">kW</span></div>
        <div class="metric"><div class="name">系统综合COP</div><span class="value" id="systemCop">--</span><span class="unit"></span></div>
        <div class="metric"><div class="name">运行冷冻水流量</div><span class="value" id="systemFlow">--</span><span class="unit">m3/h</span></div>
      </div>
    </div>
    <div class="summary">
      <div class="metric"><div class="name">当前可削减功率</div><span class="value" id="pReduce">--</span><span class="unit">kW</span></div>
      <div class="metric"><div class="name">蓄冰可释冷支撑时长</div><span class="value" id="iceSupportedDuration">--</span><span class="unit">h</span></div>
      <div class="metric"><div class="name">可转移冷量</div><span class="value" id="energy">--</span><span class="unit">kWh</span></div>
      <div class="metric"><div class="name">恢复反弹功率</div><span class="value" id="rebound">--</span><span class="unit">kW</span></div>
    </div>
    <div class="section">
      <h2>功率组成</h2>
      <div class="bar-row"><div>停止制冰削减</div><div class="track"><div id="stopBar" class="fill stop"></div></div><div id="stopVal">-- kW</div></div>
      <div class="bar-row"><div>释冰替代冷机</div><div class="track"><div id="shiftBar" class="fill shift"></div></div><div id="shiftVal">-- kW</div></div>
      <div class="bar-row"><div>供水温度上调</div><div class="track"><div id="supplyTempBar" class="fill supply"></div></div><div id="supplyTempVal">-- kW</div></div>
      <div class="bar-row"><div>恢复反弹功率</div><div class="track"><div id="reboundBar" class="fill rebound"></div></div><div id="reboundVal">-- kW</div></div>
    </div>
    <div class="section"><h2>当前判断</h2><div class="operation-summary" id="summaryText"></div></div>
    <div class="actions"><div class="section"><h2>建议操作</h2><ol id="actions"></ol></div><div class="section"><h2>约束与提醒</h2><ul id="warnings"></ul></div></div>
  </main>
</div>
<script>
const dataRows = __DATA_JSON__;
const maxIceInventoryKwh = __MAX_ICE_INVENTORY_KWH__;
const iceDischargePowerLimitKw = __ICE_DISCHARGE_POWER_LIMIT_KW__;
const designCoolingCapacityKw = __DESIGN_COOLING_CAPACITY_KW__;
const dualIceMakingCapacityKw = __DUAL_ICE_MAKING_CAPACITY_KW__;
const dualAirConditionCapacityKw = __DUAL_AIR_CONDITION_CAPACITY_KW__;
const dualIceMakingRatedOutTempC = __DUAL_ICE_MAKING_RATED_OUT_TEMP_C__;
const dualAirConditionOutTempC = __DUAL_AIR_CONDITION_OUT_TEMP_C__;
const baseAirConditionCapacityKw = __BASE_AIR_CONDITION_CAPACITY_KW__;
const baseAirConditionCop = __BASE_AIR_CONDITION_COP__;
const dualAirConditionCop = __DUAL_AIR_CONDITION_COP__;
const dualIceMakingRatedPowerKw = __DUAL_ICE_MAKING_RATED_POWER_KW__;
const waterHeatKwPerM3hC = __WATER_HEAT_KW_PER_M3H_C__;
const defaultContractSupplyTempC = __CONTRACT_SUPPLY_TEMP_C__;
const baseChillerFlowM3h = __BASE_CHILLER_FLOW_M3H__;
const dualChillerFlowM3h = __DUAL_CHILLER_FLOW_M3H__;
const baseChillerPumpPowerKw = __BASE_CHILLER_PUMP_POWER_KW__;
const dualChillerPumpPowerKw = __DUAL_CHILLER_PUMP_POWER_KW__;
const defaultTargetResponseDurationH = __TARGET_RESPONSE_DURATION_H__;
const rtToKwh = 3.517, stepH = 0.25, reserveFraction = 0.10, usableFraction = 0.85, copIce = 4.11, restoreH = 4.0;
let isAuto = true;
const fieldIds = ["cooling_load_kw","total_supply_temp_c","contract_supply_temp_c","ice_inventory_kwh","measured_ice_delta_per_step_kwh","ice_discharge_on","base_chiller_on_count","dual_chiller_on_count","dual_chiller_mode"];
const parameterFieldIds = ["target_response_duration_h"];
const displayOnlyIds = ["flow_m3h","power_kw","min_chiller_setpoint_c","current_ice_discharge_power_kw","base_chiller_power_kw","dual_chiller_power_kw"];

function init() {
  const timeSelect = document.getElementById("timeSelect");
  dataRows.forEach((row, idx) => {
    const option = document.createElement("option");
    option.value = idx;
    option.textContent = row.collect_time_iso;
    timeSelect.appendChild(option);
  });
  timeSelect.addEventListener("change", () => loadRow(Number(timeSelect.value)));
  document.getElementById("calcBtn").addEventListener("click", calculate);
  document.getElementById("latestBtn").addEventListener("click", () => { timeSelect.value = String(dataRows.length - 1); loadRow(dataRows.length - 1); });
  document.getElementById("prevTimeBtn").addEventListener("click", () => shiftTime(-1));
  document.getElementById("nextTimeBtn").addEventListener("click", () => shiftTime(1));
  document.getElementById("autoBtn").addEventListener("click", () => setInputMode(true));
  document.getElementById("manualBtn").addEventListener("click", () => setInputMode(false));
  function handleFieldChange() {
    syncIceDischargeWithDualMode();
    calculate();
  }
  fieldIds.forEach(id => document.getElementById(id).addEventListener("input", handleFieldChange));
  fieldIds.forEach(id => document.getElementById(id).addEventListener("change", handleFieldChange));
  parameterFieldIds.forEach(id => document.getElementById(id).addEventListener("input", calculate));
  parameterFieldIds.forEach(id => document.getElementById(id).addEventListener("change", calculate));
  setInputMode(true);
  timeSelect.value = String(dataRows.length - 1);
  loadRow(dataRows.length - 1);
}

function setInputMode(autoMode) {
  isAuto = autoMode;
  document.getElementById("timeSelect").disabled = !isAuto;
  document.getElementById("autoBtn").className = isAuto ? "" : "secondary";
  document.getElementById("manualBtn").className = isAuto ? "secondary" : "";
  fieldIds.forEach(id => document.getElementById(id).disabled = isAuto);
  syncIceDischargeWithDualMode();
  updateTimeButtons();
  calculate();
}

function shiftTime(step) {
  if (!isAuto) return;
  const timeSelect = document.getElementById("timeSelect");
  const current = Number(timeSelect.value);
  const next = Math.min(Math.max(current + step, 0), dataRows.length - 1);
  if (next === current) return;
  timeSelect.value = String(next);
  loadRow(next);
}

function loadRow(index) {
  const row = dataRows[index];
  [...fieldIds, ...displayOnlyIds, "ice_delta_per_step_kwh"].forEach(id => {
    const value = row[id];
    document.getElementById(id).value = value === null || value === undefined ? "" : value;
  });
  syncIceDischargeWithDualMode();
  updateTimeButtons();
  calculate();
}

function updateTimeButtons() {
  const timeSelect = document.getElementById("timeSelect");
  const index = Number(timeSelect.value);
  document.getElementById("prevTimeBtn").disabled = !isAuto || index <= 0;
  document.getElementById("nextTimeBtn").disabled = !isAuto || index >= dataRows.length - 1;
  document.getElementById("latestBtn").disabled = !isAuto || index >= dataRows.length - 1;
}

function num(id, fallback = 0) {
  const value = Number(document.getElementById(id).value);
  return Number.isFinite(value) ? value : fallback;
}

function maybeNum(id) {
  const text = document.getElementById(id).value.trim();
  if (text === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function syncIceDischargeWithDualMode() {
  const isIceMaking = document.getElementById("dual_chiller_mode").value === "ice_making";
  const discharge = document.getElementById("ice_discharge_on");
  if (isIceMaking) discharge.value = "no";
  discharge.disabled = isAuto || isIceMaking;
}

function calculate() {
  syncIceDischargeWithDualMode();
  const row = dataRows[Number(document.getElementById("timeSelect").value)] || dataRows[dataRows.length - 1];
  const state = {
    coolingLoadKw: num("cooling_load_kw"),
    powerKw: num("power_kw"),
    totalSupplyTempC: num("total_supply_temp_c", defaultContractSupplyTempC),
    contractSupplyTempC: num("contract_supply_temp_c", defaultContractSupplyTempC),
    iceInventoryKwh: num("ice_inventory_kwh"),
    measuredIceDeltaRt: num("measured_ice_delta_per_step_kwh") / rtToKwh,
    iceDischargeOn: document.getElementById("ice_discharge_on").value === "yes",
    baseOn: Math.round(num("base_chiller_on_count")),
    dualOn: Math.round(num("dual_chiller_on_count")),
    dualMode: document.getElementById("dual_chiller_mode").value,
    basePowerKw: num("base_chiller_power_kw"),
    dualPowerKw: num("dual_chiller_power_kw"),
    targetResponseH: Math.max(num("target_response_duration_h", defaultTargetResponseDurationH), 0.01),
    setpointC: maybeNum("min_chiller_setpoint_c")
  };
  state.flowM3h = isAuto ? num("flow_m3h") : activeChillerFlowM3h(state);
  document.getElementById("flow_m3h").value = state.flowM3h.toFixed(2);
  const modeResult = inferModeAndIceDelta(state);
  const powerParts = estimateStationPowerParts(state, modeResult.mode);
  if (isAuto) {
    state.pumpPowerKw = powerParts.pumpPowerKw;
    state.chillerPowerKw = Math.max(state.powerKw - state.pumpPowerKw, 0);
    if (state.dualPowerKw <= 0) {
      state.dualPowerKw = powerParts.dualChillerPowerKw;
    }
    if (state.basePowerKw <= 0 && state.chillerPowerKw > state.dualPowerKw) {
      state.basePowerKw = Math.max(state.chillerPowerKw - state.dualPowerKw, 0);
    }
  } else {
    state.chillerPowerKw = powerParts.chillerPowerKw;
    state.basePowerKw = powerParts.baseChillerPowerKw;
    state.dualPowerKw = powerParts.dualChillerPowerKw;
    state.pumpPowerKw = powerParts.pumpPowerKw;
    state.powerKw = powerParts.totalPowerKw;
    document.getElementById("power_kw").value = state.powerKw.toFixed(2);
  }
  document.getElementById("base_chiller_power_kw").value = state.basePowerKw.toFixed(2);
  document.getElementById("dual_chiller_power_kw").value = state.dualPowerKw.toFixed(2);
  state.iceDeltaRt = modeResult.effectiveIceDeltaRt;
  document.getElementById("ice_delta_per_step_kwh").value = (state.iceDeltaRt * rtToKwh).toFixed(2);
  document.getElementById("operation_mode").value = modeResult.mode;
  const loadRatio = state.coolingLoadKw / designCoolingCapacityKw;
  document.getElementById("currentTime").textContent = isAuto ? `当前数据时间：${row.collect_time_iso}` : "当前为手动输入模式";

  const iceDischargeKw = Math.max(-state.iceDeltaRt * rtToKwh / stepH, 0);
  const iceChargeKw = Math.max(state.iceDeltaRt * rtToKwh / stepH, 0);
  document.getElementById("current_ice_discharge_power_kw").value = iceDischargeKw.toFixed(2);
  const availableCoolingCapacityKw = currentAvailableCoolingCapacityKw(state, modeResult.mode, iceDischargeKw);
  state.systemCoolingKw = Math.min(Math.max(state.coolingLoadKw, 0), availableCoolingCapacityKw);
  const iceRemainingKwh = state.iceInventoryKwh;
  const reserveKwh = maxIceInventoryKwh * reserveFraction;
  const usableIceKwh = Math.max(iceRemainingKwh - reserveKwh, 0) * usableFraction;
  const availableIceKw = Math.min(usableIceKwh / state.targetResponseH, iceDischargePowerLimitKw);
  state.maxIceDischargeKw = availableIceKw;

  let stopIcePowerKw = 0, loadShiftPowerKw = 0, transferCoolingKwh = 0;
  let iceSupportedH = availableIceKw > 0 ? usableIceKwh / availableIceKw : 0;
  let responseH = 0;
  let supplyTempReductionPowerKw = 0, supplyTempReductionCoolingKw = 0, overcoolingDeltaC = 0;
  const actions = [], warnings = [modeResult.reason];
  if (state.coolingLoadKw > availableCoolingCapacityKw + 1e-6) {
    warnings.push(`当前冷负荷需求 ${state.coolingLoadKw.toFixed(1)} kW 已超过当前设备与蓄冰可提供制冷量 ${availableCoolingCapacityKw.toFixed(1)} kW，系统总制冷量按可用能力上限计算，建议增加可用机组或降低负荷侧需求。`);
  }
  if (modeResult.mode === "制冰") {
    stopIcePowerKw = iceChargeKw / copIce;
    responseH = stopIcePowerKw > 0 ? state.targetResponseH : 0;
    transferCoolingKwh = iceChargeKw * responseH;
    actions.push("停止或降低制冰负荷，直接削减双工况机组制冰电功率。");
  } else if (modeResult.mode === "基载" || modeResult.mode === "基载+双工况") {
    const replacement = iceReplacementByRunningChillers(state, availableIceKw);
    loadShiftPowerKw = replacement.reduciblePowerKw;
    responseH = replacement.replacedCoolingKw > 0 ? Math.min(state.targetResponseH, usableIceKwh / replacement.replacedCoolingKw) : 0;
    transferCoolingKwh = replacement.replacedCoolingKw * responseH;
    actions.push(`当前未释冰，但具备蓄冰替代潜力：${replacement.description}`);
  } else if (modeResult.mode === "释冰+基载" || modeResult.mode === "释冰+基载+双工况") {
    const additionalIceKw = Math.max(availableIceKw - iceDischargeKw, 0);
    const replacement = iceReplacementByRunningChillers(state, additionalIceKw);
    loadShiftPowerKw = replacement.reduciblePowerKw;
    responseH = replacement.replacedCoolingKw > 0 ? Math.min(state.targetResponseH, usableIceKwh / replacement.replacedCoolingKw) : 0;
    transferCoolingKwh = replacement.replacedCoolingKw * responseH;
    actions.push(`当前正在释冰，可评估增加释冰速率：${replacement.description}`);
  } else {
    actions.push("当前工况不适合作为自动需求响应时段，建议先核查设备状态和测点。");
  }
  const supplyTempReduction = supplyTemperatureReductionByContract(state, modeResult.mode);
  supplyTempReductionPowerKw = supplyTempReduction.reduciblePowerKw;
  supplyTempReductionCoolingKw = supplyTempReduction.replacedCoolingKw;
  overcoolingDeltaC = supplyTempReduction.overcoolingDeltaC;
  if (supplyTempReductionPowerKw > 0) {
    responseH = Math.max(responseH, state.targetResponseH);
    actions.push(`总供水温度低于合同值，可上调到${state.contractSupplyTempC.toFixed(1)}℃以减少过冷冷量：${supplyTempReduction.description}`);
  }
  const reducibleKw = Math.min(Math.max(stopIcePowerKw + loadShiftPowerKw + supplyTempReductionPowerKw, 0), Math.max(state.powerKw, 0));
  const reboundKw = transferCoolingKwh / copIce / restoreH;
  const level = classifyLevel(reducibleKw, responseH);
  if (level === "不建议响应") warnings.push("可削减功率或可响应时长不足，当前不建议参与削峰响应。");
  render({ mode: modeResult.mode, loadRatio, iceDischargeKw, iceChargeKw, usableIceKwh, availableIceKw, stopIcePowerKw, loadShiftPowerKw, supplyTempReductionPowerKw, supplyTempReductionCoolingKw, overcoolingDeltaC, reducibleKw, responseH, iceSupportedH, transferCoolingKwh, reboundKw, level, actions, warnings, state });
}

function inferModeAndIceDelta(state) {
  if (state.dualOn >= 1 && state.dualMode === "ice_making") {
    const iceMakingKw = dualIceMakingPowerKw(state);
    return { mode:"制冰", effectiveIceDeltaRt: iceMakingKw * stepH / rtToKwh, reason:`制冰判据优先成立：双工况运行台数=${state.dualOn}，双工况冷水机组工况=制冰；估算制冰功率=${iceMakingKw.toFixed(1)} kW。` };
  }
  const dischargeDelta = Math.min(state.measuredIceDeltaRt, -50);
  if (state.iceDischargeOn && state.baseOn >= 1 && state.dualOn >= 1) return { mode:"释冰+基载+双工况", effectiveIceDeltaRt:dischargeDelta, reason:`释冰判据成立：当前是否释冰=是，同时基载和双工况运行；库存差分=${(state.measuredIceDeltaRt*rtToKwh).toFixed(1)} kWh。` };
  if (state.iceDischargeOn && state.baseOn >= 1) return { mode:"释冰+基载", effectiveIceDeltaRt:dischargeDelta, reason:`释冰判据成立：当前是否释冰=是，同时基载运行；库存差分=${(state.measuredIceDeltaRt*rtToKwh).toFixed(1)} kWh。` };
  if (state.iceDischargeOn && state.baseOn < 1 && state.dualOn < 1) return { mode:"释冰", effectiveIceDeltaRt:dischargeDelta, reason:`释冰判据成立：当前是否释冰=是，主冷机未运行；库存差分=${(state.measuredIceDeltaRt*rtToKwh).toFixed(1)} kWh。` };
  if (state.baseOn >= 1 && state.dualOn >= 1) return { mode:"基载+双工况", effectiveIceDeltaRt:0, reason:`当前是否释冰=否，未满足制冰判据，按运行机组组合识别为基载+双工况。` };
  if (state.baseOn >= 1) return { mode:"基载", effectiveIceDeltaRt:0, reason:`当前是否释冰=否，未满足制冰判据，按运行机组组合识别为基载。` };
  return { mode:"异常/未定义", effectiveIceDeltaRt:0, reason:"未满足制冰、释冰或主冷机运行判据，识别为异常/未定义。" };
}

function dualIceMakingPowerKw(state) {
  if (state.dualPowerKw > 0) return state.dualPowerKw * copIce;
  return state.dualOn * dualIceMakingCapacityKw;
}

function iceReplacementByRunningChillers(state, availableIceCoolingKw) {
  let remaining = Math.min(Math.max(availableIceCoolingKw,0), Math.max(state.coolingLoadKw,0), Math.max(state.baseOn,0)*baseAirConditionCapacityKw + Math.max(state.dualOn,0)*dualAirConditionCapacityKw);
  const replacedCoolingKw = remaining;
  const dualReplaceKw = Math.min(remaining, Math.max(state.dualOn,0)*dualAirConditionCapacityKw);
  remaining -= dualReplaceKw;
  const baseReplaceKw = Math.min(remaining, Math.max(state.baseOn,0)*baseAirConditionCapacityKw);
  const reduciblePowerKw = dualReplaceKw / dualAirConditionCop + baseReplaceKw / baseAirConditionCop;
  const parts = [];
  if (dualReplaceKw > 0) parts.push(`优先替代双工况冷量${dualReplaceKw.toFixed(1)} kW`);
  if (baseReplaceKw > 0) parts.push(`再替代基载冷量${baseReplaceKw.toFixed(1)} kW`);
  if (parts.length === 0) parts.push("当前没有可被释冰替代的运行冷机冷量");
  parts.push(`折算削减电功率${reduciblePowerKw.toFixed(1)} kW`);
  return { replacedCoolingKw, reduciblePowerKw, description: parts.join("，") + "。" };
}

function supplyTemperatureReductionByContract(state, mode) {
  const supplyState = {...state};
  if (mode === "制冰") {
    supplyState.dualOn = 0;
    supplyState.flowM3h = Math.max(state.baseOn, 0) * baseChillerFlowM3h;
  }
  const overcoolingDeltaC = Math.max(state.contractSupplyTempC - state.totalSupplyTempC, 0);
  const overcoolingCoolingKw = Math.max(supplyState.flowM3h, 0) * waterHeatKwPerM3hC * overcoolingDeltaC;
  const replacement = chillerReductionByRunningChillers(supplyState, overcoolingCoolingKw, "供水温度上调");
  return { ...replacement, overcoolingDeltaC, overcoolingCoolingKw };
}

function activeChillerFlowM3h(state) {
  return Math.max(state.baseOn, 0) * baseChillerFlowM3h + Math.max(state.dualOn, 0) * dualChillerFlowM3h;
}

function currentAvailableCoolingCapacityKw(state, mode, iceDischargeKw) {
  const baseCoolingCapacityKw = Math.max(state.baseOn, 0) * baseAirConditionCapacityKw;
  const dualCoolingCapacityKw = mode === "制冰" ? 0 : Math.max(state.dualOn, 0) * dualAirConditionCapacityKw;
  return baseCoolingCapacityKw + dualCoolingCapacityKw + Math.max(iceDischargeKw, 0);
}

function estimateStationPowerParts(state, mode) {
  const baseOn = Math.max(state.baseOn, 0);
  const dualOn = Math.max(state.dualOn, 0);
  const pumpPowerKw = baseOn * baseChillerPumpPowerKw + dualOn * dualChillerPumpPowerKw;
  let baseChillerPowerKw = 0;
  let dualChillerPowerKw = 0;
  let chillerPowerKw = 0;

  if (mode === "制冰") {
    const baseCoolingCapacityKw = baseOn * baseAirConditionCapacityKw;
    const baseCoolingKw = Math.min(Math.max(state.coolingLoadKw, 0), baseCoolingCapacityKw);
    baseChillerPowerKw = baseAirConditionCop > 0 ? baseCoolingKw / baseAirConditionCop : 0;
    dualChillerPowerKw = state.dualPowerKw > 0 ? state.dualPowerKw : dualOn * dualIceMakingRatedPowerKw;
    chillerPowerKw = baseChillerPowerKw + dualChillerPowerKw;
  } else {
    const baseCapacityKw = baseOn * baseAirConditionCapacityKw;
    const dualCapacityKw = dualOn * dualAirConditionCapacityKw;
    const totalCapacityKw = baseCapacityKw + dualCapacityKw;
    const coolingToServeKw = Math.min(Math.max(state.coolingLoadKw, 0), totalCapacityKw);
    if (totalCapacityKw > 0 && coolingToServeKw > 0) {
      const baseCoolingKw = coolingToServeKw * baseCapacityKw / totalCapacityKw;
      const dualCoolingKw = coolingToServeKw * dualCapacityKw / totalCapacityKw;
      baseChillerPowerKw = baseAirConditionCop > 0 ? baseCoolingKw / baseAirConditionCop : 0;
      dualChillerPowerKw = dualAirConditionCop > 0 ? dualCoolingKw / dualAirConditionCop : 0;
      chillerPowerKw = baseChillerPowerKw + dualChillerPowerKw;
    }
  }

  return {
    baseChillerPowerKw,
    dualChillerPowerKw,
    chillerPowerKw,
    pumpPowerKw,
    totalPowerKw: chillerPowerKw + pumpPowerKw
  };
}

function chillerReductionByRunningChillers(state, reducibleCoolingKw, label) {
  let remaining = Math.min(Math.max(reducibleCoolingKw,0), Math.max(state.coolingLoadKw,0), Math.max(state.baseOn,0)*baseAirConditionCapacityKw + Math.max(state.dualOn,0)*dualAirConditionCapacityKw);
  const replacedCoolingKw = remaining;
  const dualReplaceKw = Math.min(remaining, Math.max(state.dualOn,0)*dualAirConditionCapacityKw);
  remaining -= dualReplaceKw;
  const baseReplaceKw = Math.min(remaining, Math.max(state.baseOn,0)*baseAirConditionCapacityKw);
  const reduciblePowerKw = dualReplaceKw / dualAirConditionCop + baseReplaceKw / baseAirConditionCop;
  const parts = [];
  if (dualReplaceKw > 0) parts.push(`${label}减少双工况冷量${dualReplaceKw.toFixed(1)} kW`);
  if (baseReplaceKw > 0) parts.push(`${label}减少基载冷量${baseReplaceKw.toFixed(1)} kW`);
  if (parts.length === 0) parts.push("当前没有可被削减的运行冷机冷量");
  parts.push(`折算削减电功率${reduciblePowerKw.toFixed(1)} kW`);
  return { replacedCoolingKw, reduciblePowerKw, description: parts.join("，") + "。" };
}

function classifyLevel(powerKw, durationH) {
  if (powerKw >= 1000 && durationH >= 1) return "可响应";
  if (powerKw >= 300 && durationH >= 0.5) return "有限响应";
  return "不建议响应";
}

function render(result) {
  setText("pReduce", result.reducibleKw, 1);
  setText("iceSupportedDuration", result.iceSupportedH, 3);
  setText("energy", result.transferCoolingKwh, 0);
  setText("rebound", result.reboundKw, 1);
  setText("systemPower", result.state.powerKw, 1);
  setText("chillerPower", result.state.chillerPowerKw, 1);
  setText("pumpPower", result.state.pumpPowerKw, 1);
  setText("systemCooling", result.state.systemCoolingKw, 1);
  setText("systemCop", result.state.powerKw > 0 ? result.state.systemCoolingKw / result.state.powerKw : NaN, 2);
  setText("systemFlow", result.state.flowM3h, 0);
  const badge = document.getElementById("levelBadge");
  badge.textContent = result.level;
  badge.className = "status " + (result.level === "可响应" ? "ok" : result.level === "有限响应" ? "mid" : "no");
  const maxBar = Math.max(result.stopIcePowerKw, result.loadShiftPowerKw, result.supplyTempReductionPowerKw, result.reboundKw, 1);
  setBar("stopBar", "stopVal", result.stopIcePowerKw, maxBar);
  setBar("shiftBar", "shiftVal", result.loadShiftPowerKw, maxBar);
  setBar("supplyTempBar", "supplyTempVal", result.supplyTempReductionPowerKw, maxBar);
  setBar("reboundBar", "reboundVal", result.reboundKw, maxBar);
  let supplyText = "";
  if (result.overcoolingDeltaC > 0) {
    supplyText = `总供水温度比合同值低<strong>${result.overcoolingDeltaC.toFixed(2)}℃</strong>，对应可减少过冷冷量约<strong>${result.supplyTempReductionCoolingKw.toFixed(1)} kW</strong>。`;
  } else {
    const deltaHigh = result.state.totalSupplyTempC - result.state.contractSupplyTempC;
    supplyText = `总供水温度不低于合同值，当前无供水温度上调削减项；当前比合同值高<strong>${Math.max(deltaHigh, 0).toFixed(2)}℃</strong>。`;
  }
  document.getElementById("summaryText").innerHTML = `当前工况为<strong>${result.mode}</strong>，负荷率为<strong>${(result.loadRatio*100).toFixed(1)}%</strong>。当前按<strong>${result.state.targetResponseH.toFixed(2)} h</strong>响应任务评估。用于计算的单步冰量变化为<strong>${(result.state.iceDeltaRt*rtToKwh).toFixed(1)} kWh</strong>，可用蓄冰冷量约<strong>${result.usableIceKwh.toFixed(0)} kWh</strong>。${supplyText}`;
  fillList("actions", result.actions);
  fillList("warnings", result.warnings.length ? result.warnings : ["暂无明显约束风险。"]);
}
function setText(id, value, digits) { document.getElementById(id).textContent = Number.isFinite(value) ? value.toFixed(digits) : "--"; }
function setBar(barId, valueId, value, maxValue) { document.getElementById(barId).style.width = `${Math.min(value/maxValue*100,100)}%`; document.getElementById(valueId).textContent = `${value.toFixed(1)} kW`; }
function fillList(id, items) { const list = document.getElementById(id); list.innerHTML = ""; items.forEach(text => { const li=document.createElement("li"); li.textContent=text; list.appendChild(li); }); }
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
