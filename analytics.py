import io
import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

# Sentiment keywords (Russian)
POSITIVE_WORDS = {
    'спасибо', 'круто', 'класс', 'отлично', 'супер', 'молодец', 'здорово', 'прекрасно',
    'замечательно', 'восхитительно', 'люблю', 'нравится', 'рад', 'счастлив', 'весело',
    'хорошо', 'лучший', 'красиво', 'интересно', 'удачи', 'благодарю', 'топ', 'огонь',
    'кайф', 'респект', 'обожаю', 'радость', '❤️', '😊', '😍', '🔥', '👍', '💪', '🎉'
}

NEGATIVE_WORDS = {
    'плохо', 'ужас', 'отстой', 'ненавижу', 'грустно', 'печально', 'злой', 'бесит',
    'раздражает', 'достало', 'надоело', 'страшно', 'боюсь', 'тревожно', 'депрессия',
    'одиноко', 'больно', 'обидно', 'несправедливо', 'жалко', 'устал', 'сложно',
    'проблема', 'помогите', 'sos', 'срочно', 'кризис', 'тяжело', '😢', '😭', '😔', '💔', '😡'
}

URGENT_WORDS = {
    'срочно', 'помогите', 'sos', 'помощь', 'спасите', 'экстренно', 'кризис',
    'суицид', 'самоубийство', 'не хочу жить', 'конец', 'умереть', 'больше не могу',
    'насилие', 'бьют', 'угрожают', 'опасность', '🆘', '⚠️'
}


def analyze_sentiment(text: str) -> dict:
    if not text:
        return {"sentiment": "neutral", "score": 0, "urgent": False}
    
    text_lower = text.lower()
    words = set(re.findall(r'\w+', text_lower))
    
    # Check for urgency first
    urgent = bool(words & URGENT_WORDS) or any(uw in text_lower for uw in URGENT_WORDS)
    
    positive_count = len(words & POSITIVE_WORDS) + sum(1 for pw in POSITIVE_WORDS if pw in text)
    negative_count = len(words & NEGATIVE_WORDS) + sum(1 for nw in NEGATIVE_WORDS if nw in text)
    
    total = positive_count + negative_count
    if total == 0:
        score = 0
        sentiment = "neutral"
    else:
        score = (positive_count - negative_count) / total
        if score > 0.2:
            sentiment = "positive"
        elif score < -0.2:
            sentiment = "negative"
        else:
            sentiment = "neutral"
    
    return {
        "sentiment": sentiment,
        "score": round(score, 2),
        "urgent": urgent,
        "positive_count": positive_count,
        "negative_count": negative_count
    }


def generate_heatmap(hourly_data: dict[int, int]) -> io.BytesIO:
    """Generate activity heatmap by hour"""
    plt.figure(figsize=(12, 4))
    
    hours = list(range(24))
    values = [hourly_data.get(h, 0) for h in hours]
    
    colors = plt.cm.YlOrRd(np.array(values) / max(max(values), 1))
    
    bars = plt.bar(hours, values, color=colors, edgecolor='white', linewidth=0.5)
    
    plt.xlabel('Час', fontsize=12)
    plt.ylabel('Сообщений', fontsize=12)
    plt.title('🔥 Активность по часам', fontsize=14, fontweight='bold')
    plt.xticks(hours, [f'{h:02d}' for h in hours], fontsize=9)
    plt.grid(axis='y', alpha=0.3)
    
    # Highlight peak hours
    if values:
        max_val = max(values)
        for i, (bar, val) in enumerate(zip(bars, values)):
            if val == max_val and val > 0:
                bar.set_edgecolor('red')
                bar.set_linewidth(2)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', 
                facecolor='white', edgecolor='none')
    buf.seek(0)
    plt.close()
    
    return buf


def generate_weekly_heatmap(daily_hourly_data: dict[int, dict[int, int]]) -> io.BytesIO:
    """Generate weekly heatmap (days x hours)"""
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    hours = list(range(24))
    
    data = np.zeros((7, 24))
    for day in range(7):
        for hour in range(24):
            data[day][hour] = daily_hourly_data.get(day, {}).get(hour, 0)
    
    fig, ax = plt.subplots(figsize=(14, 5))
    
    im = ax.imshow(data, cmap='YlOrRd', aspect='auto')
    
    ax.set_xticks(range(24))
    ax.set_xticklabels([f'{h:02d}' for h in hours], fontsize=8)
    ax.set_yticks(range(7))
    ax.set_yticklabels(days, fontsize=10)
    
    ax.set_xlabel('Час', fontsize=12)
    ax.set_ylabel('День недели', fontsize=12)
    ax.set_title('📅 Тепловая карта активности', fontsize=14, fontweight='bold')
    
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Сообщений', fontsize=10)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    plt.close()
    
    return buf


def generate_sentiment_chart(sentiment_data: dict[str, int]) -> io.BytesIO:
    """Generate sentiment pie chart"""
    labels = []
    sizes = []
    colors_map = {
        'positive': '#4CAF50',
        'neutral': '#9E9E9E', 
        'negative': '#F44336'
    }
    emoji_map = {
        'positive': '😊 Позитивные',
        'neutral': '😐 Нейтральные',
        'negative': '😢 Негативные'
    }
    colors = []
    
    for sentiment in ['positive', 'neutral', 'negative']:
        if sentiment_data.get(sentiment, 0) > 0:
            labels.append(emoji_map[sentiment])
            sizes.append(sentiment_data[sentiment])
            colors.append(colors_map[sentiment])
    
    if not sizes:
        sizes = [1]
        labels = ['Нет данных']
        colors = ['#9E9E9E']
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct='%1.1f%%',
        startangle=90, explode=[0.02] * len(sizes)
    )
    
    for autotext in autotexts:
        autotext.set_fontsize(11)
        autotext.set_fontweight('bold')
    
    ax.set_title('📊 Анализ тональности сообщений', fontsize=14, fontweight='bold')
    
    total = sum(sizes)
    plt.figtext(0.5, 0.02, f'Всего сообщений: {total}', ha='center', fontsize=10)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    plt.close()
    
    return buf


def generate_activity_trend(daily_data: list[tuple[str, int]]) -> io.BytesIO:
    """Generate activity trend line chart"""
    if not daily_data:
        daily_data = [(datetime.now().strftime('%Y-%m-%d'), 0)]
    
    dates = [datetime.strptime(d[0], '%Y-%m-%d') for d in daily_data]
    values = [d[1] for d in daily_data]
    
    fig, ax = plt.subplots(figsize=(12, 5))
    
    ax.fill_between(dates, values, alpha=0.3, color='#2196F3')
    ax.plot(dates, values, color='#1976D2', linewidth=2, marker='o', markersize=4)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))
    
    plt.xticks(rotation=45)
    ax.set_xlabel('Дата', fontsize=12)
    ax.set_ylabel('Сообщений', fontsize=12)
    ax.set_title('📈 Динамика сообщений', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    # Stats
    if values:
        avg = sum(values) / len(values)
        ax.axhline(y=avg, color='orange', linestyle='--', alpha=0.7, label=f'Среднее: {avg:.1f}')
        ax.legend()
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    plt.close()
    
    return buf
