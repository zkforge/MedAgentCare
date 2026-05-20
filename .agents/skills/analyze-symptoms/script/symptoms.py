from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import split_terms, success


SYSTEM_RULES = {
    "respiratory": {
        "label": "呼吸系统",
        "keywords": ["咳嗽", "咳痰", "呼吸困难", "胸闷", "喘", "喉咙痛"],
        "direction": "呼吸道感染、哮喘/慢阻肺急性发作或其他呼吸系统问题",
    },
    "cardiovascular": {
        "label": "心血管系统",
        "keywords": ["胸痛", "心悸", "胸闷", "气短", "冒冷汗", "晕厥"],
        "direction": "心血管风险，需要结合年龄、基础病和发作特点评估",
    },
    "neurologic": {
        "label": "神经系统",
        "keywords": ["头痛", "眩晕", "视力模糊", "偏瘫", "抽搐", "意识不清"],
        "direction": "神经系统问题，若突发、剧烈或伴神经定位体征需急诊评估",
    },
    "digestive": {
        "label": "消化系统",
        "keywords": ["腹痛", "腹泻", "恶心", "呕吐", "便血", "食欲差"],
        "direction": "胃肠道感染、炎症、消化系统功能紊乱或其他腹部疾病",
    },
    "infectious": {
        "label": "感染/全身反应",
        "keywords": ["发热", "寒战", "乏力", "肌肉酸痛", "高热"],
        "direction": "感染或炎症反应，需要结合体温、持续时间和伴随症状判断",
    },
}


def analyze_symptoms(symptoms: str, duration_days: int = 0):
    """Analyze symptom clusters and likely involved body systems."""
    terms = split_terms(symptoms)
    haystack = symptoms.strip()
    matched_systems = []

    for key, rule in SYSTEM_RULES.items():
        matched = [keyword for keyword in rule["keywords"] if keyword in haystack]
        if matched:
            matched_systems.append(
                {
                    "system": key,
                    "label": rule["label"],
                    "matched_symptoms": matched,
                    "possible_direction": rule["direction"],
                }
            )

    if not matched_systems:
        matched_systems.append(
            {
                "system": "general",
                "label": "未明确归类",
                "matched_symptoms": terms,
                "possible_direction": "当前症状信息不足，建议补充持续时间、严重程度、诱因和伴随症状。",
            }
        )

    red_flags = []
    for keyword in ["胸痛", "呼吸困难", "意识不清", "偏瘫", "剧烈头痛", "颈部僵硬"]:
        if keyword in haystack:
            red_flags.append(keyword)

    if duration_days >= 7:
        red_flags.append("持续时间较长")

    lines = ["症状模式分析："]
    for item in matched_systems:
        lines.append(
            f"- {item['label']}：命中 {', '.join(item['matched_symptoms'])}；"
            f"可能方向：{item['possible_direction']}"
        )
    if red_flags:
        lines.append(f"需要重点关注的风险信号：{', '.join(red_flags)}")
    lines.append("说明：以上是症状模式分析，不构成确诊。")

    return success(
        "\n".join(lines),
        symptoms=terms,
        matched_systems=matched_systems,
        red_flags=red_flags,
    )
