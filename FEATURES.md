# Madar – Extra Features

Things we add **after the core works** (see the demo goal in `CONTRACT.md`).

- [ ] AI: type a rule in plain English/Arabic and get a preview
- [ ] Absent teacher: suggest substitutes
- [ ] Arabic interface
- [ ] Export timetable to PDF
- [ ] Soft preferences: e.g. avoid a teacher's back-to-back lessons, spread a subject across the week
- [ ] Manual edit: swap two lessons by hand, with a check that the hard rules still hold
- [ ] Explain failures: when generation fails, say which rule or teacher load causes the conflict
- [ ] Teacher workload view: lessons per teacher per day
- [ ] Undo / save timetable versions
- [ ] Analytics: workload per teacher, gaps in teacher days, hard subjects by period, lessons per class per day, and a rule check (`GET /api/analytics`, all computed in Python)
- [ ] *(Stretch)* AI insights: the AI explains those analytics in English or Arabic (`POST /api/analytics/insights`). Code computes the numbers, the AI only explains them
- [ ] *(Stretch)* PDF / messy-file import using AI, always with a preview (same preview-then-confirm flow as the `.xlsx` import in `CONTRACT.md`; the AI only fills the preview, the solver still only reads the database)
