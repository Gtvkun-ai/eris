"""Facade ontology trong cấu trúc mới.

Logic thật vẫn nằm ở `memory.predicate_ontology` để không phá code cũ. File này
chỉ đặt đúng chỗ kiến trúc: claims/ontology.py.
"""

from ..predicate_ontology import *  # noqa: F401,F403
