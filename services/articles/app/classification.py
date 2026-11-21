import re

# First matching category wins. Specific vulnerability and malware terms take priority.
RULES = {
    "vulnerabilities": r"\bcve(?:-\d{4}-\d+)?\b|\bvulnerabilit(?:y|ies)\b|\bexploit(?:s|ed|ing)?\b|\bzero[- ]day\b",
    "malware": r"\b(?:ransomware|malware|trojans?|botnets?|infostealers?|spyware)\b",
    "data-breaches": r"\b(?:breach(?:es|ed)?|leak(?:s|ed)?|exposed data|data exposure)\b",
    "cyberattacks": r"\b(?:ddos|phishing|cyberattacks?|cyber attacks?|supply chain attack)\b",
    "research": r"\b(?:research|study|analysis|researchers)\b",
    "software-security": r"\b(?:software security|secure coding|hardening|security updates?|authentication|patches)\b",
}
PATTERNS = [(category, re.compile(pattern, re.IGNORECASE)) for category, pattern in RULES.items()]


def classify(title: str, summary: str | None, tags: list[str]) -> str:
    text = " ".join([title, summary or "", *tags])
    return next((category for category, pattern in PATTERNS if pattern.search(text)), "other")
