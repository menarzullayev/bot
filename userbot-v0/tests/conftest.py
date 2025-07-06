# tests/conftest.py
"""
Pytest uchun umumiy sozlamalar va fixture'lar fayli.
Bu fayldagi sozlamalar `tests/` papkasidagi barcha testlarga avtomatik qo'llaniladi.
"""

import sys
from pathlib import Path
import pytest

@pytest.fixture(scope="session", autouse=True)
def setup_project_root():
    """
    Test sessiyasi boshlanishidan oldin loyiha ildiz papkasini
    Pythonning import yo'llariga (sys.path) qo'shadi.
    Bu barcha test fayllarida `from bot...` yoki `from core...` kabi
    mutlaq importlardan muammosiz foydalanishni ta'minlaydi.
    """
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))