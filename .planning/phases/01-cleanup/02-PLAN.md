---
phase: 01-cleanup
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/Step5Interaction.vue
  - backend/app/api/simulation.py
autonomous: true
must_haves:
  truths:
    - Step5Interaction.vue line 12 shows `'REF-2024-X92'` as a literal fallback in the template — it should be absent (show nothing) when reportId prop is not provided
    - simulation.py line 460 has a concatenation bug where `"项目"` (Chinese for "project") was accidentally prepended to an otherwise-English error string, producing `"项目Missing simulation requirement..."` — this must be replaced with a clean English-only string
  artifacts:
    - Step5Interaction.vue with no hardcoded REF-2024-X92 fallback
    - simulation.py line 460 with a clean English-only error message
  key_links: []
---

<objective>
Fix two isolated bugs: a hardcoded placeholder report ID in the frontend template, and a Chinese/English
string concatenation bug in a backend API error response.

Purpose: Remove the fake UI artifact visible to end-users and fix the garbled API error message.
Output: One template line changed, one backend error string cleaned up.
</objective>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@frontend/src/components/Step5Interaction.vue
@backend/app/api/simulation.py
</context>

<tasks>

<task type="auto">
  <name>Task 1.3: Remove hardcoded REF-2024-X92 fallback in Step5Interaction.vue</name>
  <files>frontend/src/components/Step5Interaction.vue</files>
  <action>
At line 12 in the `<template>` block, the report ID is displayed with a hardcoded fallback:

```html
              <span class="report-id">ID: {{ reportId || 'REF-2024-X92' }}</span>
```

When `reportId` is null/undefined, this shows a fake reference number. Replace with a conditional
render that hides the element entirely when no ID is present:

Find (line 12):
```html
              <span class="report-id">ID: {{ reportId || 'REF-2024-X92' }}</span>
```

Replace with:
```html
              <span v-if="reportId" class="report-id">ID: {{ reportId }}</span>
```

This keeps the exact same appearance when a real reportId is passed, and renders nothing when it is absent.
  </action>
  <verify>
Run: `grep -n "REF-2024-X92" frontend/src/components/Step5Interaction.vue`
Expected: no output.
Run: `grep -n "report-id" frontend/src/components/Step5Interaction.vue`
Expected: the span now has `v-if="reportId"` and no fallback string.
  </verify>
  <done>
- The string literal `'REF-2024-X92'` does not appear anywhere in the file.
- The report-id span uses `v-if="reportId"` and renders `{{ reportId }}` directly with no fallback.
  </done>
</task>

<task type="auto">
  <name>Task 1.4: Fix concatenation bug in simulation.py line ~460</name>
  <files>backend/app/api/simulation.py</files>
  <action>
At line 460, the error response contains a garbled string produced by accidentally leaving a Chinese
prefix on an otherwise-English message:

```python
                "error": "项目Missing simulation requirement description (simulation_requirement)"
```

`"项目"` is Chinese for "project" — it was a leftover from an incomplete translation.

Find (exact string at line 460):
```python
                "error": "项目Missing simulation requirement description (simulation_requirement)"
```

Replace with:
```python
                "error": "Missing simulation requirement description (simulation_requirement)"
```
  </action>
  <verify>
Run: `grep -n "项目Missing" backend/app/api/simulation.py`
Expected: no output.
Run: `grep -n "Missing simulation requirement" backend/app/api/simulation.py`
Expected: one match at the corrected line with no Chinese prefix.
  </verify>
  <done>
- No occurrence of `"项目Missing"` exists in simulation.py.
- The error string reads `"Missing simulation requirement description (simulation_requirement)"`.
  </done>
</task>

</tasks>

<success_criteria>
1. `grep -rn "REF-2024-X92" frontend/src/components/Step5Interaction.vue` returns nothing.
2. `grep -n "项目Missing" backend/app/api/simulation.py` returns nothing.
3. `grep -n "Missing simulation requirement" backend/app/api/simulation.py` returns exactly one match with no Chinese characters on that line.
4. The Vue template still renders `ID: {{ reportId }}` when a reportId is provided (verified by reading the changed line).
</success_criteria>
