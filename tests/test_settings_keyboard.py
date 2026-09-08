from src.bot.keyboards import get_advanced_planning_keyboard, get_settings_keyboard


def _labels(kb):
    return {btn.text for row in kb.inline_keyboard for btn in row}


class TestSettingsKeyboard:
    def test_has_no_advanced_buttons(self):
        labels = _labels(get_settings_keyboard())
        assert "📌 Обязательные" not in labels
        assert "🏦 Кубышка" not in labels
        assert "🎯 Хотелка" not in labels
        assert "🐖 Округление" not in labels

    def test_has_advanced_planning_button(self):
        labels = _labels(get_settings_keyboard())
        assert "🧾 Дополнительное планирование" in labels

    def test_has_core_buttons(self):
        labels = _labels(get_settings_keyboard())
        assert "🔄 Изменить бюджет" in labels
        assert "📅 День старта" in labels
        assert "🗂 Категории" in labels


class TestAdvancedPlanningKeyboard:
    def test_has_mandatory_savings_wishlist(self):
        labels = _labels(get_advanced_planning_keyboard())
        assert "📌 Обязательные" in labels
        assert "🏦 Кубышка" not in labels
        assert "🎯 Хотелка" not in labels

    def test_has_no_rounding(self):
        labels = _labels(get_advanced_planning_keyboard())
        assert "🐖 Округление" not in labels
