from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import split_terms, success


EMERGENCY_KEYWORDS = {
    "胸痛": "胸痛可能提示心血管急症",
    "呼吸困难": "呼吸困难可能提示呼吸或循环系统急症",
    "昏厥": "昏厥需要排查严重循环或神经系统问题",
    "意识不清": "意识改变属于高危表现",
    "剧烈头痛": "突发或剧烈头痛需要排查脑血管等急症",
    "偏瘫": "偏瘫可能提示卒中",
    "抽搐": "抽搐需要及时医学评估",
    "大出血": "大量出血需要紧急处理",
}

HIGH_KEYWORDS = {
    "高热": "高热持续不退需要就医评估",
    "颈部僵硬": "颈部僵硬合并发热/头痛需警惕中枢感染",
    "持续呕吐": "持续呕吐可能导致脱水或提示严重病因",
    "视力模糊": "突然视力变化需要排查眼科或神经系统问题",
    "心悸": "明显心悸需要评估心律问题",
}

MEDIUM_KEYWORDS = {
    "发热": "发热需要结合持续时间和伴随症状观察",
    "咳嗽": "咳嗽持续或加重需关注呼吸道感染",
    "腹痛": "腹痛需要结合部位、持续时间和伴随症状",
    "头痛": "头痛持续、加重或伴随神经症状时需就医",
}


def assess_risk(symptoms: str, age: int = 0, duration_days: int = 0):
    """Assess symptom risk level using explicit triage rules."""
    terms = split_terms(symptoms)
    haystack = symptoms.strip()
    reasons = []

    risk_level = "low"
    urgency = "routine"

    for keyword, reason in EMERGENCY_KEYWORDS.items():
        if keyword in haystack:
            reasons.append(reason)
            risk_level = "emergency"
            urgency = "immediate"

    if risk_level != "emergency":
        for keyword, reason in HIGH_KEYWORDS.items():
            if keyword in haystack:
                reasons.append(reason)
                risk_level = "high"
                urgency = "same_day"

    if risk_level == "low":
        for keyword, reason in MEDIUM_KEYWORDS.items():
            if keyword in haystack:
                reasons.append(reason)
                risk_level = "medium"
                urgency = "monitor"

    if age >= 65 and risk_level in {"low", "medium"}:
        reasons.append("老年患者同样症状风险更高，建议降低就医阈值")
        risk_level = "high" if risk_level == "medium" else "medium"
        urgency = "same_day" if risk_level == "high" else "monitor"

    if duration_days >= 7 and risk_level == "low":
        reasons.append("症状持续超过 7 天，建议进一步评估")
        risk_level = "medium"
        urgency = "monitor"

    if not reasons:
        reasons.append("未命中明确高危规则，但仍需结合个人病史和症状变化判断")

    if risk_level == "emergency":
        recommendation = "建议立即就医或拨打急救电话，不要等待线上咨询结果。"
    elif risk_level == "high":
        recommendation = "建议尽快线下就医，尤其是症状加重或伴随基础疾病时。"
    elif risk_level == "medium":
        recommendation = "建议密切观察，若持续、加重或出现高危伴随症状，应及时就医。"
    else:
        recommendation = "可先观察和基础护理，但如症状变化或不确定，应咨询医生。"

    answer = (
        f"风险等级：{risk_level}\n"
        f"紧急程度：{urgency}\n"
        f"判断依据：{'；'.join(reasons)}\n"
        f"建议：{recommendation}"
    )
    return success(
        answer,
        symptoms=terms,
        risk_level=risk_level,
        urgency=urgency,
        reasons=reasons,
        recommendation=recommendation,
    )
