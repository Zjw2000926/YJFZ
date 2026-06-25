"""生命体征阈值规则"""

import json, os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VITAL_PATH = os.path.join(BASE,"triage_data","rules","vital_thresholds_v1.json")

_cache = None

def _load():
    global _cache
    if _cache is None:
        with open(VITAL_PATH,encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache

def parse_value(raw):
    """从测量值字符串中提取数字"""
    if raw is None:
        return None
    if isinstance(raw,(int,float)):
        return float(raw)
    s = str(raw).replace("mmHg","").replace("次/min","").replace("%","").replace("℃","").replace("分","").strip()
    try:
        return float(s.split("/")[0] if "/" in s else s)
    except:
        return None

from .models import LEVEL_RANK as _LEVEL_RANK

def check_vital_threshold(vital_id, value, data):
    """检查单个生命体征是否触发阈值规则。返回最大规则命中。"""
    thresholds = _load().get("thresholds",{}).get(vital_id,[])
    if value is None:
        return None
    val = parse_value(value)
    if val is None:
        return None
    result = None
    for t in thresholds:
        op = t.get("operator")
        tv = t.get("value")
        hit = False
        if op == "<" and val < tv:
            hit = True
        elif op == "<=" and val <= tv:
            hit = True
        elif op == ">" and val > tv:
            hit = True
        elif op == ">=" and val >= tv:
            hit = True
        if hit:
            if result is None or _LEVEL_RANK.get(result.get("minimum_level","Ⅳ级"),4) > _LEVEL_RANK.get(t.get("minimum_level","Ⅳ级"),4):
                result = t
    return result

def evaluate_vitals(measurements, data):
    """评估所有测量的生命体征，返回命中的规则列表和最低安全等级。"""
    hits = []
    min_level = "Ⅳ级"
    for m in measurements:
        vid = m.get("id","")
        val = m.get("value")
        if not val:
            continue
        r = check_vital_threshold(vid, val, data)
        if r:
            hits.append({"rule_id":r["rule_id"],"level":r["minimum_level"],"category":"vital",
                         "evidence":f"{m.get('label',vid)} {val} 触发阈值 {r.get('label','')}","vital_id":vid,"value":str(val),"threshold":r.get("value")})
            if _LEVEL_RANK.get(r["minimum_level"],4) < _LEVEL_RANK.get(min_level,4):
                min_level = r["minimum_level"]
    return hits, min_level
