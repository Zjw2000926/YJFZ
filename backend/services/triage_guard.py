"""预检分诊专用安全检查

检测：
1. 分诊答案泄露（Ⅰ级/Ⅱ级/红区/黄区/绿色通道）
2. 教学反馈（你应该问/你漏问了）
3. 诊断化表述
4. 病例外生命体征
5. 输出过长
"""

# 分诊答案泄露（患者绝对不能说的）
TRIAGE_LEAK_PATTERNS = [
    # 分诊等级
    "Ⅰ级", "Ⅱ级", "Ⅲ级", "Ⅳ级", "1级", "2级", "3级", "4级",
    "一级", "二级", "三级", "四级", "濒危", "危重",
    # 就诊区域
    "红区", "黄区", "绿区", "抢救区", "监护区",
    # 处置
    "绿色通道", "胸痛优先",
    # 角色暴露
    "按分诊标准", "根据分诊", "我这种情况应该",
    # 诊断化
    "我可能是", "我这是", "应该是",
]

# 教学反馈
TRIAGE_TEACHING_PATTERNS = [
    "你应该问", "你漏了", "你还没有问", "建议你",
    "下一个问", "接着问", "你问得好", "继续问",
]

# 输出过长阈值
MAX_TRIAGE_REPLY_LEN = 400

# 兜底
FALLBACK = "这个我说不太清楚，您能再问得具体一点吗？"


def check_triage_leak(reply: str) -> list:
    """检测分诊答案泄露"""
    violations = []
    for pattern in TRIAGE_LEAK_PATTERNS:
        if pattern in reply:
            violations.append(f"分诊泄露: {pattern}")
    return violations


def check_triage_teaching(reply: str) -> list:
    """检测教学反馈"""
    violations = []
    for pattern in TRIAGE_TEACHING_PATTERNS:
        if pattern in reply:
            violations.append(f"教学反馈: {pattern}")
    return violations


def check_triage_long(reply: str) -> bool:
    """检测输出过长"""
    return len(reply) > MAX_TRIAGE_REPLY_LEN


def sanitize_triage_reply(reply: str) -> tuple:
    """分诊回复安全检查。返回 (sanitized, violations)"""
    violations = []

    leaks = check_triage_leak(reply)
    violations.extend(leaks)

    teaching = check_triage_teaching(reply)
    violations.extend(teaching)

    if check_triage_long(reply):
        violations.append(f"输出过长: {len(reply)}chars")
        reply = reply[:300] + "..."

    if leaks or teaching:
        return FALLBACK, violations

    return reply, violations
