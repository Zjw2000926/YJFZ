"""预检分诊规则引擎 V3

模块职责：
- engine: 总入口
- models: 数据结构
- vital_rules: 生命体征阈值
- symptom_rules: 高危症状规则
- special_population_rules: 特殊人群
- severity: 等级比较、低/高估判断
- explanation: 规则命中→反馈文本
"""
from .engine import evaluate
from .models import RuleResult, RuleHit
