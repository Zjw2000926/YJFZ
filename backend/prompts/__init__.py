"""预检分诊虚拟患者提示词模块。"""

from .triage_patient_system_prompt import TRIAGE_PATIENT_SYSTEM_PROMPT, VARIANT_STYLES

# 兼容旧名称：现阶段系统提示词已经收敛到预检分诊患者 prompt。
FIXED_SYSTEM_PROMPT = TRIAGE_PATIENT_SYSTEM_PROMPT

__all__ = [
    "TRIAGE_PATIENT_SYSTEM_PROMPT",
    "VARIANT_STYLES",
    "FIXED_SYSTEM_PROMPT",
]
