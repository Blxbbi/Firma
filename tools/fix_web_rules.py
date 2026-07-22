with open('engine/providers/pi_provider.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """                    web_rules = (
                        f"\\n\\n[Web Research] You MAY perform web research (max "
                        f"{FIRMA_RESEARCH_WEB_MAX_QUERIES} queries, "
                        f"{FIRMA_RESEARCH_WEB_TIMEOUT_S}s timeout per query) to supplement your findings. "
                        f"Use `curl` or `wget` for HTTP requests only. For every external claim, add a source URL. "
                        f"If web research is unavailable or fails, continue with local findings only and note "
                        f"'Web research unavailable' in your brief.\\n\\n"
                    )"""

new = """                    web_rules = (
                        f"\\n\\n[Web Research] You MAY perform web research (max "
                        f"{FIRMA_RESEARCH_WEB_MAX_QUERIES} queries, "
                        f"{FIRMA_RESEARCH_WEB_TIMEOUT_S}s timeout per query) to supplement your findings. "
                        f"Use `curl` or `wget` for HTTP requests only. For every external claim, add a source URL. "
                        f"If web research is unavailable or fails, continue with local findings only and note "
                        f"'Web research unavailable: <reason>' in your brief.\\n\\n"
                        f"[Contract] You MUST include the section "
                        f"'## External research (sources)' in your brief. "
                        f"If you cannot provide sources, write exactly: "
                        f"'Web research unavailable: <reason>'. "
                        f"Missing this section is non-fatal and will be logged as non-compliance, not as task failure.\\n\\n"
                    )"""

if old in content:
    content = content.replace(old, new)
    with open('engine/providers/pi_provider.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('OLD TEXT NOT FOUND')
    idx = content.find('web_rules = (')
    print(repr(content[idx:idx+600]))
