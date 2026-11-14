import pytest

from ai import normalize as n

SUBJECTS = [{"id": 4, "name": "Math", "name_ar": "الرياضيات"}, {"id": 8, "name": "PE", "name_ar": "التربية البدنية"},
            {"id": 1, "name": "Islamic Education", "name_ar": "التربية الإسلامية"}]


@pytest.mark.parametrize("text,expected", [("الأحد", 0), ("يوم الاثنين", 1), ("Tue", 2), ("الاربعاء", 3), ("thursday", 4),
                                           (2, 2), ("Friday", None), ("الجمعة", None), (7, None), ("", None)])
def test_day(text, expected):
    assert n.day(text) == expected


@pytest.mark.parametrize("text,expected", [("٧", 7), ("7", 7), (7.0, 7), ("3rd", 3), (0, None), (8, None), ("x", None), (True, None)])
def test_period(text, expected):
    assert n.period(text) == expected


@pytest.mark.parametrize("text,expected", [("math", 4), ("الرياضيات", 4), ("رياضيات", 4), ("pe", 8), ("Physical Education", 8),
                                           ("التربية البدنية", 8), ("تربية بدنية", 8), ("اسلامية", 1), (4, 4), ("history", None), (None, None)])
def test_subject_id(text, expected):
    assert n.subject_id(text, SUBJECTS) == expected


def test_class_name():
    assert n.class_name("٢/٥") == "2/5" and n.class_name("2 / 5") == "2/5" and n.class_name("two") is None
