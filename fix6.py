import re

file_path = r'e:\Projects\QP\dsatm-qpgen-backend\app\academic\generation.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Cast desired_module to string when checking module_co_mapping
# Look for: if desired_module is not None and module_co_mapping and desired_module in module_co_mapping:
old_co_mapping = '''        # Incorporate dynamic module-to-CO mapping
        if desired_module is not None and module_co_mapping and desired_module in module_co_mapping:
            mapped_cos = [
                str(co).strip().upper()
                for co in module_co_mapping[desired_module]
                if str(co).strip()
            ]'''
new_co_mapping = '''        # Incorporate dynamic module-to-CO mapping
        if desired_module is not None and module_co_mapping and str(desired_module) in module_co_mapping:
            mapped_cos = [
                str(co).strip().upper()
                for co in module_co_mapping[str(desired_module)]
                if str(co).strip()
            ]'''
content = content.replace(old_co_mapping, new_co_mapping)


# Also fix module_bloom_mapping for safety
old_bloom_mapping = '''        if desired_module is not None and module_bloom_mapping and desired_module in module_bloom_mapping:
            mapped_blooms = [
                str(b).strip().upper()
                for b in module_bloom_mapping[desired_module]
                if str(b).strip()
            ]'''
new_bloom_mapping = '''        if desired_module is not None and module_bloom_mapping and str(desired_module) in module_bloom_mapping:
            mapped_blooms = [
                str(b).strip().upper()
                for b in module_bloom_mapping[str(desired_module)]
                if str(b).strip()
            ]'''
content = content.replace(old_bloom_mapping, new_bloom_mapping)


# Fix 2: _build_heuristic_question_text to sound less robotic
# We will replace the entire _build_heuristic_question_text function
heuristic_old = '''def _build_heuristic_question_text(slot: PlannedQuestionSlot) -> str:
    verbs = VTU_PROFILE.verbs.get(slot.bloom_level, VTU_PROFILE.verbs["L2"])
    verb = verbs[0]
    topic = slot.topic_name
    detail = slot.detail

    if detail:
        detail = re.sub(r"\\b(module|unit|chapter)\\s*\\d+\\b", " ", detail, flags=re.IGNORECASE)
        detail = _normalize_text(detail).strip(" .,:;-")
    if detail in _GENERIC_DETAIL_PHRASES:
        detail = None

    if slot.family == "workflow":
        return f"{verb} the workflow of {topic} with a neat diagram and suitable example."
    if slot.family == "comparison":
        if detail:
            return f"{verb} {topic} with respect to {detail}."
        return f"{verb} the important characteristics of {topic}."
    if slot.family == "application":
        if slot.bloom_level == "L3":
            return f"{verb} {topic} to solve a suitable problem and show the major steps involved."
        if detail:
            return f"{verb} the application of {topic} in {detail}."
        return f"{verb} {topic} for a representative problem scenario."
    if slot.family == "analysis":
        if detail:
            return f"{verb} {topic} and discuss its significance in {detail}."
        return f"{verb} {topic} with proper academic justification."
    if slot.family == "design":
        if detail:
            return f"{verb} a solution based on {topic} for {detail}."
        return f"{verb} a suitable solution using {topic}."
    if slot.bloom_level in {"L1", "L2"}:
        return f"{verb} {topic} with suitable examples."
    if detail:
        return f"{verb} {topic} in the context of {detail}."
    return f"{verb} {topic} with proper justification."'''

heuristic_new = '''def _build_heuristic_question_text(slot: PlannedQuestionSlot) -> str:
    verbs = VTU_PROFILE.verbs.get(slot.bloom_level, VTU_PROFILE.verbs["L2"])
    verb = verbs[0]
    topic = slot.topic_name
    
    if slot.family == "workflow":
        return f"{verb} the architecture or workflow of {topic}."
    if slot.family == "comparison":
        return f"{verb} the key concepts and properties of {topic}."
    if slot.family == "application":
        return f"{verb} the practical methodology of {topic}."
    if slot.family == "analysis":
        return f"{verb} the academic principles behind {topic}."
    if slot.family == "design":
        return f"{verb} the structural design patterns for {topic}."
    if slot.bloom_level in {"L1", "L2"}:
        return f"{verb} the core concept of {topic}."
    return f"{verb} {topic} in detail."'''

content = content.replace(heuristic_old, heuristic_new)


# Fix 3: Lower `min_confidence` to `0.60`
confidence_old = '''def _is_publishable_question(question: GeneratedQuestion, min_confidence: float = 0.72) -> bool:'''
confidence_new = '''def _is_publishable_question(question: GeneratedQuestion, min_confidence: float = 0.60) -> bool:'''
content = content.replace(confidence_old, confidence_new)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied backend fixes to generation.py")
