"""
HDEC DAILY NEWS 자동 생성기
매일 오후 1시 자동 실행 → 뉴스 수집 → 필터링 → TOP 10 선정 → HTML 생성
"""

import csv
import json
import os
import re
import requests
from datetime import datetime, timedelta
from html import unescape

# ──────────────────────────────────────
# 설정
# ──────────────────────────────────────
KEYWORD = "현대건설"

NAVER_CLIENT_ID = "4EpC74MmQmbBp2bpWpI5"
NAVER_CLIENT_SECRET = "uxqj17VklI"

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(OUTPUT_DIR, "news_top10.html")
CSV_PATH = os.path.join(OUTPUT_DIR, "현대건설_뉴스_종합.csv")
SHOWN_PATH = os.path.join(OUTPUT_DIR, "shown_articles.json")


# ──────────────────────────────────────
# 1) 네이버 뉴스 API 수집
# ──────────────────────────────────────
def collect_naver_news():
    articles = []
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    # 오전 실행(~12시): 전일 16시 이후 기사만 수집
    # 오후 실행(12시~): 당일 08시 이후 기사만 수집
    now = datetime.now()
    if now.hour < 12:
        cutoff = now.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)

    for start in range(1, 1000, 100):
        params = {"query": KEYWORD, "display": 100, "start": start, "sort": "date"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [API 오류] {e}")
            break

        items = data.get("items", [])
        if not items:
            break

        stop = False
        for item in items:
            try:
                pub_date = datetime.strptime(
                    item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"
                ).replace(tzinfo=None)
            except ValueError:
                continue

            if pub_date < cutoff:
                stop = True
                break

            title = re.sub(r"<.*?>", "", unescape(item.get("title", "")))
            link = item.get("originallink") or item.get("link", "")
            description = re.sub(r"<.*?>", "", unescape(item.get("description", "")))

            articles.append({
                "date": pub_date.strftime("%Y-%m-%d"),
                "title": title,
                "link": link,
                "source": "네이버뉴스",
                "description": description,
            })

        if stop:
            break

    return articles


# ──────────────────────────────────────
# 2) 중복 제거
# ──────────────────────────────────────
def remove_duplicates(articles):
    seen = set()
    unique = []
    for art in articles:
        clean = re.sub(r"[^가-힣a-zA-Z0-9]", "", art["title"])
        key = clean[:20]
        if key not in seen:
            seen.add(key)
            unique.append(art)
    return unique



# ──────────────────────────────────────
# 2-b) 이전 표시 기사 제외 (중복 방지)
# ──────────────────────────────────────
def load_shown_articles():
    if not os.path.exists(SHOWN_PATH):
        return set()
    try:
        with open(SHOWN_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cutoff = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        return set(k for k, v in data.items() if v >= cutoff)
    except Exception:
        return set()


def save_shown_articles(articles):
    existing = {}
    if os.path.exists(SHOWN_PATH):
        try:
            with open(SHOWN_PATH, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            pass
    cutoff = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    existing = {k: v for k, v in existing.items() if v >= cutoff}
    today = datetime.now().strftime('%Y-%m-%d')
    for art in articles:
        key = re.sub(r"[^가-힣a-zA-Z0-9]", "", art["title"])[:30]
        existing[key] = today
    with open(SHOWN_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def exclude_shown(articles):
    shown = load_shown_articles()
    if not shown:
        return articles
    filtered = []
    for art in articles:
        key = re.sub(r"[^가-힣a-zA-Z0-9]", "", art["title"])[:30]
        if key not in shown:
            filtered.append(art)
    return filtered


# ──────────────────────────────────────
# 3) 불필요 기사 제거
# ──────────────────────────────────────
EXCLUDE_KEYWORDS = [
    # 스포츠
    "배구", "V리그", "챔프전", "플레이오프", "실바", "세트스코어", "득점",
    "서브에이스", "현대캐피탈", "GS칼텍스", "한국도로공사", "흥국생명",
    "감독", "선수", "경기에서", "프로배구",
    # 단순 주가
    "장중", "주가,",
    # 하자 건수 단순 나열
    "하자 판정 1위", "하자 최다", "하자 건수 최다",
]

# 현대건설이 핵심이 아닌 기사 패턴
WEAK_MENTION_PATTERNS = [
    r"명예회장.*현대건설에 입사",
    r"현대건설에 입사해.*비서실장",
    r"펀드매니저.*리포트",
    r"ETF.*브랜드",
]


def filter_irrelevant(articles):
    filtered = []
    for art in articles:
        text = art["title"] + " " + art.get("description", "")

        # 스포츠/주가/하자 제외
        if any(kw in text for kw in EXCLUDE_KEYWORDS):
            continue

        # 약한 언급 제외
        if any(re.search(pat, text) for pat in WEAK_MENTION_PATTERNS):
            continue

        filtered.append(art)
    return filtered


# ──────────────────────────────────────
# 4) TOP 10 스코어링
# ──────────────────────────────────────
ENERGY_KEYWORDS = [
    ("원전", 15), ("EPC", 12), ("해상풍력", 15), ("부유식", 12),
    ("SMR", 14), ("수소", 10), ("CCUS", 12), ("에너지", 8),
    ("태양광", 8), ("풍력", 8), ("LNG", 10), ("가스처리", 10),
    ("데이터센터", 8), ("원자력", 12), ("페르미", 15), ("FEED", 12),
    ("신재생", 8), ("탄소", 6), ("전력", 6),
]

IMPACT_KEYWORDS = [
    ("비상", 12), ("공사비", 10), ("리스크", 10), ("수급난", 12),
    ("지연", 8), ("공문", 10), ("위기", 8), ("전쟁", 10),
    ("봉쇄", 12), ("폭등", 10), ("품귀", 10), ("중동", 8),
    ("이란", 8), ("원가", 8), ("인상", 6), ("차질", 8),
    ("비용", 6), ("노조", 8), ("교섭", 8), ("파업", 10),
    ("GTX", 10), ("LOC", 8), ("증액", 8),
    ("해외", 6), ("CEO", 6), ("대표", 4),
    ("경쟁", 6), ("단독", 8), ("타운화", 10),
    # 정비사업
    ("재건축", 12), ("재개발", 12), ("리모델링", 12), ("정비사업", 12),
    ("조합", 8), ("시공사 선정", 10), ("수주전", 10), ("정비구역", 8),
    ("관리처분", 8), ("사업시행", 8), ("철거", 6), ("이주", 6),
    ("조합원", 6), ("분담금", 8), ("입찰", 8), ("응찰", 8),
]

NOVELTY_KEYWORDS = [
    ("단독", 10), ("첫", 8), ("최초", 10), ("신규", 6),
    ("협약", 8), ("MOU", 8), ("공동개발", 8), ("파트너", 6),
    ("착수", 6), ("전환", 6), ("확장", 4),
]

# 이미 수주 완료된 반복 기사 감점
COMPLETED_BID_PATTERNS = [
    (r"신길1구역.*수주", -20),
    (r"수주.*신길1구역", -20),
    (r"선착순.*계약", -15),
    (r"선착순.*분양", -15),
    (r"힐스테이트 선암", -12),
    (r"스타트업.*공모전", -10),
    (r"오픈.*이노베이션", -10),
    (r"비전 필름", -10),
    (r"OWN THE", -10),
]


def score_article(art):
    text = art["title"] + " " + art.get("description", "")
    score = 0

    for kw, pts in ENERGY_KEYWORDS:
        if kw in text:
            score += pts

    for kw, pts in IMPACT_KEYWORDS:
        if kw in text:
            score += pts

    for kw, pts in NOVELTY_KEYWORDS:
        if kw in text:
            score += pts

    for pat, pts in COMPLETED_BID_PATTERNS:
        if re.search(pat, text):
            score += pts  # pts is negative

    # 제목에 '현대건설'이 직접 포함되면 가산
    if "현대건설" in art["title"]:
        score += 5

    return score


def select_top10(articles):
    scored = [(score_article(a), a) for a in articles]
    scored.sort(key=lambda x: x[0], reverse=True)

    # 상위 10개, 같은 주제 중복 방지
    selected = []
    seen_keys = set()
    for sc, art in scored:
        clean = re.sub(r"[^가-힣]", "", art["title"])[:15]
        if clean not in seen_keys:
            seen_keys.add(clean)
            art["_score"] = sc
            selected.append(art)
        if len(selected) >= 10:
            break

    return selected


# ──────────────────────────────────────
# 5) 태그 분류
# ──────────────────────────────────────
def classify_article(art):
    text = art["title"] + " " + art.get("description", "")
    tags = []
    section = "전략"

    energy_words = ["원전", "해상풍력", "SMR", "수소", "CCUS", "에너지", "풍력",
                    "태양광", "LNG", "가스", "페르미", "FEED", "EPC", "데이터센터",
                    "신재생", "부유식"]
    risk_words = ["비상", "리스크", "위기", "전쟁", "봉쇄", "폭등", "품귀",
                  "수급난", "지연", "공사비", "원가", "인상", "차질", "노조", "교섭"]
    compete_words = ["경쟁", "수주전", "입찰", "응찰", "단독", "타운화", "압구정",
                    "재건축", "재개발", "리모델링", "정비사업", "조합", "시공사 선정",
                    "정비구역", "관리처분", "사업시행", "분담금"]
    infra_words = ["GTX", "인프라", "LOC", "착공", "공공"]
    strategy_words = ["해외", "CEO", "전략", "확장", "협약", "MOU", "공동개발"]

    if any(w in text for w in energy_words):
        tags.append(("에너지", "energy"))
        section = "에너지 사업"
    if any(w in text for w in risk_words):
        tags.append(("리스크", "risk"))
        if section != "에너지 사업":
            section = "리스크 모니터링"
    if any(w in text for w in compete_words):
        tags.append(("수주경쟁", "compete"))
        if section not in ("에너지 사업", "리스크 모니터링"):
            section = "수주 경쟁 & 전략"
    if any(w in text for w in infra_words):
        tags.append(("인프라", "infra"))
    if any(w in text for w in strategy_words):
        tags.append(("전략", "strategy"))

    if not tags:
        tags.append(("전략", "strategy"))
        section = "수주 경쟁 & 전략"

    return tags[:3], section


# ──────────────────────────────────────
# 6) HTML 생성
# ──────────────────────────────────────
def generate_html(articles):
    today = datetime.now().strftime("%Y년 %m월 %d일")
    today_short = datetime.now().strftime("%Y.%m.%d")

    # 섹션별 분류
    sections = {"에너지 사업": [], "리스크 모니터링": [], "수주 경쟁 & 전략": []}
    for i, art in enumerate(articles):
        tags, section = classify_article(art)
        art["_tags"] = tags
        art["_section"] = section
        art["_rank"] = i + 1
        if section in sections:
            sections[section].append(art)
        else:
            sections["수주 경쟁 & 전략"].append(art)

    def priority_class(art):
        text = art["title"] + " " + art.get("description", "")
        if any(w in text for w in ["비상", "긴급", "전쟁", "봉쇄", "폭등", "원전", "EPC", "해상풍력"]):
            return "priority-critical"
        if any(w in text for w in ["리스크", "위기", "지연", "인상", "해외", "CEO"]):
            return "priority-high"
        return "priority-medium"

    def make_tags_html(tags):
        return "".join(f'<span class="tag tag-{cls}">{name}</span>' for name, cls in tags)

    def get_source(link):
        import urllib.parse
        domain = urllib.parse.urlparse(link).netloc.replace("www.", "")
        source_map = {
            "theguru.co.kr": "더구루", "kpenews.com": "한국정경신문",
            "newsway.co.kr": "뉴스웨이", "newspim.com": "뉴스핌",
            "socialvalue.kr": "소셜밸류", "newsis.com": "뉴시스",
            "bizhankook.com": "비즈한국", "bigtanews.co.kr": "빅터뉴스",
            "investchosun.com": "인베스트조선", "etoday.co.kr": "이투데이",
            "mk.co.kr": "매일경제", "hankyung.com": "한국경제",
            "yna.co.kr": "연합뉴스", "sedaily.com": "서울경제",
            "dnews.co.kr": "대한경제", "chosun.com": "조선일보",
            "khan.co.kr": "경향신문", "mt.co.kr": "머니투데이",
            "asiae.co.kr": "아시아경제", "view.asiae.co.kr": "아시아경제",
            "fnnews.com": "파이낸셜뉴스", "edaily.co.kr": "이데일리",
            "dt.co.kr": "디지털타임스", "news1.kr": "뉴스1",
            "ajunews.com": "아주경제", "sbs.co.kr": "SBS",
            "biz.sbs.co.kr": "SBS비즈", "jtbc.co.kr": "JTBC",
            "news.jtbc.co.kr": "JTBC",
        }
        return source_map.get(domain, domain)

    def escape(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    cards_html = ""
    section_order = ["에너지 사업", "리스크 모니터링", "수주 경쟁 & 전략"]
    for sec in section_order:
        arts = sections.get(sec, [])
        if not arts:
            continue
        cards_html += f'<div class="section-divider">{sec}</div>\n'
        for art in arts:
            tags_html = make_tags_html(art["_tags"])
            cards_html += f"""
        <article class="card">
            <div class="card-inner">
                <div class="card-body">
                    <div class="card-tags">{tags_html}</div>
                    <h2 class="card-title">
                        <a href="{escape(art['link'])}" target="_blank">{escape(art['title'])}</a>
                    </h2>
                    <p class="card-desc">{escape(art.get('description', '')[:150])}</p>
                    <div class="card-footer">
                        <span class="card-source">{get_source(art['link'])} · {art['date']}</span>
                        <a class="card-link" href="{escape(art['link'])}" target="_blank">
                            기사 원문
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M17 7H7M17 7v10"/></svg>
                        </a>
                    </div>
                </div>
            </div>
        </article>
"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HDEC DAILY NEWS - {today}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;800&display=swap');
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Noto Sans KR', sans-serif; background: #f5f5f5; color: #222; min-height: 100vh; }}

        /* Header - 현대건설 CI */
        .header {{ background: #ffffff; padding: 28px 0; border-bottom: 3px solid #15ad60; }}
        .header-content {{ max-width: 960px; margin: 0 auto; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; }}
        .header-left {{ display: flex; align-items: center; gap: 16px; }}
        .logo-img {{ height: 36px; }}
        .header-divider {{ width: 1px; height: 32px; background: #ddd; }}
        .header-title {{ display: flex; flex-direction: column; }}
        .header h1 {{ font-size: 22px; font-weight: 800; color: #1a1a1a; letter-spacing: 1px; }}
        .header-right {{ display: flex; align-items: center; gap: 16px; }}
        .header-info {{ display: flex; flex-direction: column; align-items: flex-end; }}
        .header-date {{ font-size: 14px; color: #555; font-weight: 500; }}
        .header-schedule {{ font-size: 11px; color: #aaa; margin-top: 2px; }}
        .badge {{ display: inline-block; background: #15ad60; color: #fff; padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}

        /* Main */
        .container {{ max-width: 960px; margin: 0 auto; padding: 28px 24px 60px; }}

        /* Legend */
        .legend {{ display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 12px; color: #666; }}
        .legend-dot {{ width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }}

        /* Section */
        .section-divider {{ display: flex; align-items: center; gap: 10px; margin: 28px 0 16px; font-size: 13px; font-weight: 700; color: #15ad60; letter-spacing: 0.5px; }}
        .section-divider::after {{ content: ''; flex: 1; height: 1px; background: #ddd; }}

        /* Cards */
        .card {{ background: #ffffff; border: 1px solid #e8e8e8; border-radius: 8px; margin-bottom: 12px; overflow: hidden; transition: all 0.2s ease; }}
        .card:hover {{ border-color: #15ad60; box-shadow: 0 2px 12px rgba(21, 173, 96, 0.08); }}
        .card-inner {{ padding: 20px 24px; }}
        .card-body {{ flex: 1; min-width: 0; }}
        .card-tags {{ display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }}
        .tag {{ font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 3px; letter-spacing: 0.2px; }}
        .tag-energy {{ background: #e8f8ef; color: #15ad60; }}
        .tag-risk {{ background: #fdecea; color: #d32f2f; }}
        .tag-compete {{ background: #e3f2fd; color: #1976d2; }}
        .tag-infra {{ background: #f3e5f5; color: #7b1fa2; }}
        .tag-strategy {{ background: #fff8e1; color: #f9a825; }}
        .card-title {{ font-size: 16px; font-weight: 600; color: #1a1a1a; line-height: 1.6; margin-bottom: 6px; }}
        .card-title a {{ color: inherit; text-decoration: none; transition: color 0.2s; }}
        .card-title a:hover {{ color: #15ad60; }}
        .card-desc {{ font-size: 13px; color: #777; line-height: 1.7; margin-bottom: 12px; }}
        .card-footer {{ display: flex; align-items: center; justify-content: space-between; }}
        .card-source {{ font-size: 12px; color: #aaa; }}
        .card-link {{ display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #15ad60; text-decoration: none; font-weight: 600; }}
        .card-link:hover {{ color: #0d8c4d; }}
        .card-link svg {{ width: 13px; height: 13px; }}

        /* Footer */
        .footer {{ text-align: center; padding: 28px 24px; border-top: 1px solid #e0e0e0; font-size: 11px; color: #aaa; background: #fff; }}

        @media (max-width: 640px) {{
            .header-content {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
            .header h1 {{ font-size: 20px; }}
            .card-inner {{ padding: 16px; }}
            .card-title {{ font-size: 14px; }}
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="header-left">
                <img src="logo.png" alt="HYUNDAI E&C" class="logo-img">
                <div class="header-divider"></div>
                <div class="header-title">
                    <h1>DAILY NEWS</h1>
                </div>
            </div>
            <div class="header-right">
                <div class="header-info">
                    <span class="header-date">{today}</span>
                    <span class="header-schedule">매일 오전 7:30 / 오후 1:00 자동 업데이트</span>
                </div>
                <span class="badge">TOP 10</span>
            </div>
        </div>
    </header>
    <main class="container">
        <div class="legend">
            <div class="legend-item"><div class="legend-dot" style="background:#15ad60"></div>에너지</div>
            <div class="legend-item"><div class="legend-dot" style="background:#d32f2f"></div>리스크</div>
            <div class="legend-item"><div class="legend-dot" style="background:#1976d2"></div>수주경쟁</div>
            <div class="legend-item"><div class="legend-dot" style="background:#7b1fa2"></div>인프라</div>
            <div class="legend-item"><div class="legend-dot" style="background:#f9a825"></div>전략</div>
        </div>
        {cards_html}
    </main>
    <footer class="footer">
        <img src="logo.png" alt="HYUNDAI E&C" style="height:24px; margin-bottom:8px;">
        <p>HDEC AI 뉴스 큐레이션 · 네이버 뉴스 API 기반 · {today_short} 자동 생성</p>
    </footer>
</body>
</html>"""

    return html


# ──────────────────────────────────────
# 메인
# ──────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  HDEC DAILY NEWS 자동 생성")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 1) 수집
    print("[1/6] 네이버 뉴스 API 수집 중...")
    articles = collect_naver_news()
    print(f"  → {len(articles)}건 수집")

    # 2) 중복 제거
    print("[2/6] 중복 제거 중...")
    articles = remove_duplicates(articles)
    print(f"  → {len(articles)}건")

    # 3) 불필요 기사 필터링
    print("[3/6] 불필요 기사 필터링 중...")
    articles = filter_irrelevant(articles)
    print(f"  → {len(articles)}건")

    # 4) 이전 표시 기사 제외
    print("[4/6] 이전 표시 기사 제외 중...")
    before = len(articles)
    articles = exclude_shown(articles)
    print(f"  → {before - len(articles)}건 제외, {len(articles)}건 남음")

    # 5) TOP 10 선정
    print("[5/6] TOP 10 선정 중...")
    top10 = select_top10(articles)
    print(f"  → TOP 10 선정 완료")
    for i, art in enumerate(top10, 1):
        print(f"     [{i}] (점수:{art['_score']}) {art['title'][:50]}")

    # 6) HTML 생성
    print("[6/6] HTML 생성 중...")
    html = generate_html(top10)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  → 저장 완료: {HTML_PATH}")

    save_shown_articles(top10)

    # CSV도 저장
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "source", "title", "link", "description"])
        writer.writeheader()
        for art in articles:
            writer.writerow({
                "date": art.get("date", ""),
                "source": art.get("source", ""),
                "title": art.get("title", ""),
                "link": art.get("link", ""),
                "description": art.get("description", ""),
            })

    print(f"\n  완료! HTML: {HTML_PATH}")


if __name__ == "__main__":
    main()
