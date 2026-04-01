"""
HDEC DAILY NEWS 자동 생성기
매일 오후 1시 자동 실행 → 뉴스 수집 → 필터링 → TOP 10 선정 → HTML 생성
"""

import csv
import json
import os
import re
import requests
from datetime import datetime, timedelta, timezone
KST = timezone(timedelta(hours=9))
from html import unescape

# ──────────────────────────────────────
# 설정
# ──────────────────────────────────────
SEARCH_KEYWORDS = [
    "현대건설", "삼성물산 건설", "DL이앤씨", "대우건설", "GS건설",
    "롯데건설", "포스코이앤씨",
    "건설사 수주", "시공사 선정", "재건축 시공사", "재개발 수주", "성수 재개발",
    "원전 건설", "해상풍력 건설", "인프라 착공",
    "건설 공사비", "건설 리스크", "건설 안전사고", "중대재해 건설", "건설 규제", "건설공제",
]

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
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    now = datetime.now(KST)
    if now.hour < 12:
        cutoff = now.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)

    # 기사별 등장 횟수 추적 (여러 키워드에 걸리면 = 화제성 높음)
    seen_links = {}  # link -> article dict
    hit_count = {}   # link -> 몇 개 키워드에서 등장했는지

    for keyword in SEARCH_KEYWORDS:
        print(f"    검색: '{keyword}'")
        kw_count = 0
        for start in range(1, 400, 100):
            params = {"query": keyword, "display": 100, "start": start, "sort": "date"}
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"    [API 오류] {e}")
                break

            items = data.get("items", [])
            if not items:
                break

            stop = False
            for item in items:
                try:
                    pub_date = datetime.strptime(
                        item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"
                    ).astimezone(KST)
                except ValueError:
                    continue

                if pub_date < cutoff:
                    stop = True
                    break

                title = re.sub(r"<.*?>", "", unescape(item.get("title", "")))
                link = item.get("originallink") or item.get("link", "")
                description = re.sub(r"<.*?>", "", unescape(item.get("description", "")))

                if link not in seen_links:
                    seen_links[link] = {
                        "date": pub_date.strftime("%Y-%m-%d"),
                        "title": title,
                        "link": link,
                        "source": "네이버뉴스",
                        "description": description,
                    }
                    hit_count[link] = 0
                    kw_count += 1
                hit_count[link] += 1

            if stop:
                break
        print(f"    → {kw_count}건 신규")

    articles = []
    for link, art in seen_links.items():
        art["_hits"] = hit_count[link]
        articles.append(art)

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
        cutoff = (datetime.now(KST) - timedelta(days=3)).strftime('%Y-%m-%d')
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
    cutoff = (datetime.now(KST) - timedelta(days=3)).strftime('%Y-%m-%d')
    existing = {k: v for k, v in existing.items() if v >= cutoff}
    today = datetime.now(KST).strftime('%Y-%m-%d')
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
    # 주식/주가
    "장중", "주가", "특징주", "관련주", "건설주", "테마주", "급등주", "상한가", "하한가",
    # 조합 내부 분쟁 (건설사 리스크 아님)
    "조합장 해임", "조합장 선거", "비대위", "총회 무산",
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

        # 7대사 외 건설사가 주체인 기사 제외
        OTHER_BUILDERS = ["두산건설", "한화건설", "코오롱글로벌", "HDC현대산업",
                          "SK에코플랜트", "호반건설", "태영건설", "한신공영",
                          "금호건설", "쌍용건설", "반도건설", "대광건영"]
        TARGET_BUILDERS = ["현대건설", "삼성물산", "DL이앤씨", "대우건설", "GS건설",
                           "롯데건설", "포스코이앤씨"]
        title_only = art["title"]
        # 제목에 타사만 있고 7대사는 없으면 제외
        has_other = any(b in title_only for b in OTHER_BUILDERS)
        has_target = any(b in title_only for b in TARGET_BUILDERS)
        if has_other and not has_target:
            continue

        # 건설업과 관련 없는 기사 제외
        construction_signals = [
            "건설", "시공", "수주", "재건축", "재개발", "리모델링", "분양",
            "공사", "착공", "준공", "설계", "도급", "하도급", "원전", "풍력",
            "인프라", "EPC", "플랜트", "정비사업", "조합", "아파트",
            "주택", "부동산", "디벨로퍼", "시행사", "발주", "입찰",
        ]
        if not any(kw in text for kw in construction_signals):
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
]

# 대형사 수주 키워드
ORDER_KEYWORDS = [
    ("수주", 12), ("입찰", 10), ("응찰", 10), ("낙찰", 12),
    ("시공사 선정", 12), ("시공권", 10), ("수주전", 10),
    ("재건축", 10), ("재개발", 10), ("리모델링", 10), ("정비사업", 10),
    ("사옥", 8), ("신축", 6), ("도급", 8), ("턴키", 8),
    ("책임준공", 8), ("계약", 6), ("단독", 8),
    ("경쟁", 6), ("타운화", 10),
    ("조합", 6), ("분담금", 6), ("관리처분", 6),
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

    for kw, pts in ORDER_KEYWORDS:
        if kw in text:
            score += pts

    for kw, pts in NOVELTY_KEYWORDS:
        if kw in text:
            score += pts

    for pat, pts in COMPLETED_BID_PATTERNS:
        if re.search(pat, text):
            score += pts  # pts is negative

    # 대형 건설사 제목 언급 가산
    MAJOR_BUILDERS = ["현대건설", "삼성물산", "DL이앤씨", "대우건설", "GS건설",
                      "롯데건설", "포스코이앤씨"]
    builder_in_title = sum(1 for b in MAJOR_BUILDERS if b in art["title"])
    if builder_in_title:
        score += 10 * builder_in_title  # 대형사 제목 언급 시 +10, 복수 언급 시 추가 가산
    if "현대건설" in art["title"]:
        score += 5  # 현대건설은 추가 가산

    # 화제성 가산: 여러 키워드 검색에 걸린 기사 = 업계 전반에서 주목
    hits = art.get("_hits", 1)
    if hits >= 3:
        score += 15
    elif hits >= 2:
        score += 8

    # 주요 매체 가산 (트래픽 높은 언론사)
    MAJOR_OUTLETS = [
        "mk.co.kr", "hankyung.com", "yna.co.kr", "sedaily.com",
        "chosun.com", "donga.com", "joongang.co.kr", "khan.co.kr",
        "hani.co.kr", "mt.co.kr", "asiae.co.kr", "fnnews.com",
        "edaily.co.kr", "news1.kr", "newsis.com", "sbs.co.kr",
        "kbs.co.kr", "mbc.co.kr", "jtbc.co.kr", "ytn.co.kr",
    ]
    link = art.get("link", "")
    if any(outlet in link for outlet in MAJOR_OUTLETS):
        score += 6

    return score


def _title_keywords(title):
    """제목에서 핵심 명사 키워드 집합 추출"""
    clean = re.sub(r"[^가-힣a-zA-Z0-9]", " ", title)
    words = set(w for w in clean.split() if len(w) >= 2)
    return words


def _is_similar(title, seen_titles):
    """기존 선정 기사와 유사한지 판별 (키워드 50% 이상 겹치면 유사)"""
    kw_new = _title_keywords(title)
    if not kw_new:
        return False
    for prev_title in seen_titles:
        kw_prev = _title_keywords(prev_title)
        if not kw_prev:
            continue
        overlap = len(kw_new & kw_prev)
        shorter = min(len(kw_new), len(kw_prev))
        if shorter > 0 and overlap / shorter >= 0.5:
            return True
    return False


def select_top10(articles):
    """각 섹션별로 독립 랭킹 후 상위 기사 선정"""
    sections = ["대형사 수주", "에너지 사업", "리스크 모니터링"]
    SECTION_COUNTS = {"대형사 수주": 4, "에너지 사업": 3, "리스크 모니터링": 3}
    TARGET_BUILDERS = ["현대건설", "삼성물산", "DL이앤씨", "대우건설", "GS건설",
                       "롯데건설", "포스코이앤씨"]

    # 섹션별로 기사 분류
    buckets = {s: [] for s in sections}
    for art in articles:
        sc = score_article(art)
        art["_score"] = sc
        _, section = classify_article(art)
        if section in buckets:
            buckets[section].append(art)

    # 각 섹션 내에서 점수순 정렬 → 유사기사 제거 → 상위 N건 선정
    selected = []
    for sec in sections:
        pool = sorted(buckets[sec], key=lambda a: a["_score"], reverse=True)
        picked = []
        seen_titles = []

        if sec == "대형사 수주":
            # 대형사 수주: 7대사 제목 언급 기사를 우선 배치
            builder_pool = [a for a in pool if any(b in a["title"] for b in TARGET_BUILDERS)]
            other_pool = [a for a in pool if not any(b in a["title"] for b in TARGET_BUILDERS)]
            for art in builder_pool + other_pool:
                if len(picked) >= SECTION_COUNTS[sec]:
                    break
                if _is_similar(art["title"], seen_titles):
                    continue
                picked.append(art)
                seen_titles.append(art["title"])
        elif sec == "리스크 모니터링":
            # 리스크 섹션: 수주성 기사 제외
            order_noise = ["수주", "입찰", "시공��� 선정", "시공권", "재건축", "재개발",
                           "리모델링", "정비사업", "사옥", "분양"]
            for art in pool:
                if len(picked) >= SECTION_COUNTS[sec]:
                    break
                if _is_similar(art["title"], seen_titles):
                    continue
                if any(w in art["title"] for w in order_noise):
                    continue
                picked.append(art)
                seen_titles.append(art["title"])
        else:
            for art in pool:
                if len(picked) >= SECTION_COUNTS[sec]:
                    break
                if _is_similar(art["title"], seen_titles):
                    continue
                picked.append(art)
                seen_titles.append(art["title"])

        selected.extend(picked)

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
    risk_words = [
        # 기존: 원자재/공사비
        "비상", "리스크", "위기", "전쟁", "봉쇄", "폭등", "품귀",
        "수급난", "지연", "공사비", "원가", "인상", "차질", "노조", "교섭",
        # 안전
        "사망", "사고", "붕괴", "화재", "안전사고", "중대재해", "산업재해", "안전관리",
        # 정책/법/규제
        "규제", "법개정", "시행령", "제재", "과징금", "영업정지", "입찰제한",
        "노란봉투법", "중대재해처벌법", "하도급법", "건설산업기본법",
        # 노동/파업
        "파업", "쟁의", "임금체불", "하도급", "불법파견",
        # 금융/경영 리스크
        "부도", "워크아웃", "유동성", "적자", "손실", "PF", "미분양",
    ]
    compete_words = ["수주", "수주전", "입찰", "응찰", "낙찰", "단독", "시공사 선정",
                    "재건축", "재개발", "리모델링", "정비사업", "사옥", "신축",
                    "도급", "계약", "턴키", "설계시공", "책임준공"]
    infra_words = ["GTX", "인프라", "LOC", "착공", "공공"]
    strategy_words = ["해외", "CEO", "전략", "확장", "협약", "MOU", "공동개발"]

    title = art["title"]
    has_energy = any(w in text for w in energy_words)
    has_risk = any(w in text for w in risk_words)
    # 정비사업 판단은 제목 기준 (본문에 살짝 언급된 것은 무시)
    # 대형사 수주 판단: 제목에 수주/입찰 관련 or 대형 건설사명 + 수주성 키워드
    major_builders = ["현대건설", "삼성물산", "DL이앤씨", "대우건설", "GS건설",
                      "롯데건설", "포스코이앤씨"]
    order_words = ["수주", "입찰", "응찰", "낙찰", "시공사", "시공권", "선정",
                   "재건축", "재개발", "리모델링", "정비사업", "사옥", "신축",
                   "도급", "계약", "턴키", "책임준공"]
    has_builder_in_title = any(b in title for b in major_builders)
    has_order_in_title = any(w in title for w in order_words)
    # 대형사명 + 본문 수주 키워드만으로는 부족 → 제목�� 수주성 키워드 필수
    is_order = has_order_in_title
    has_compete = any(w in title for w in compete_words)

    if has_energy:
        tags.append(("에너지", "energy"))
    if has_risk:
        tags.append(("리스크", "risk"))
    if has_compete or is_order:
        tags.append(("수주경쟁", "compete"))
    # 인프라/전략 태그 미사용

    # 섹션 결정 우선순위: 에너지 > 리스크 > 대형사 수주
    if has_energy:
        section = "에너지 사업"
    elif has_risk:
        section = "리스크 모니터링"
    elif is_order or has_compete:
        section = "대형사 수주"
    else:
        section = "대형사 수주"

    if not tags:
        tags.append(("수주경쟁", "compete"))

    return tags[:3], section


# ──────────────────────────────────────
# 6) HTML 생성
# ──────────────────────────────────────
def generate_html(articles):
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    today_short = datetime.now(KST).strftime("%Y.%m.%d")

    # 섹션별 분류
    sections = {"대형사 수주": [], "에너지 사업": [], "리스크 모니터링": []}
    for i, art in enumerate(articles):
        tags, section = classify_article(art)
        # 섹션에 맞는 태그만 표시
        section_tag = {
            "대형사 수주": ("수주경쟁", "compete"),
            "에너지 사업": ("에너지", "energy"),
            "리스크 모니터링": ("리스크", "risk"),
        }
        art["_tags"] = [section_tag.get(section, tags[0] if tags else ("수주경쟁", "compete"))]
        art["_section"] = section
        art["_rank"] = i + 1
        if section in sections:
            sections[section].append(art)
        else:
            sections["대형사 수주"].append(art)

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
    section_order = ["대형사 수주", "에너지 사업", "리스크 모니터링"]
    for sec in section_order:
        arts = sections.get(sec, [])
        if not arts:
            continue
        section_desc = {"대형사 수주": "대형 건설사 수주·입찰·시공사 선정 소식", "에너지 사업": "원전·SMR·해상풍력·수소 등 에너지 인프라 동향", "리스크 모니터링": "공사비·안전사고·정책 변경·금융리스크 등 건설사 영향 이슈"}
        desc = section_desc.get(sec, "")
        divider = '<div class="section-divider"><span>' + sec + '</span><span class="section-desc">' + desc + '</span></div>'
        cards_html += divider + chr(10)
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


        /* Main */
        .container {{ max-width: 960px; margin: 0 auto; padding: 28px 24px 60px; }}

        /* Legend */
        .legend {{ display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; align-items: center; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 12px; color: #666; }}
        .legend-dot {{ width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }}
        .legend-criteria {{ margin-left: auto; font-size: 14px; color: #555; font-weight: 500; white-space: nowrap; }}

        /* Section */
        .section-divider {{ display: flex; align-items: center; gap: 10px; margin: 28px 0 16px; font-size: 13px; font-weight: 700; color: #15ad60; letter-spacing: 0.5px; }}
        .section-divider::after {{ content: ''; flex: 1; height: 1px; background: #ddd; }}
        .section-desc {{ font-size: 11px; font-weight: 400; color: #999; margin-left: auto; white-space: nowrap; }}

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

            </div>
        </div>
    </header>
    <main class="container">
        <div class="legend">
            <div class="legend-item"><div class="legend-dot" style="background:#1976d2"></div>수주경쟁</div>
            <div class="legend-item"><div class="legend-dot" style="background:#15ad60"></div>에너지</div>
            <div class="legend-item"><div class="legend-dot" style="background:#d32f2f"></div>리스크</div>
            <span class="legend-criteria">네이버 뉴스 API 기반 · 화제성 + 업계 영향도 스코어링 · 섹션별 상위 기사 자동 선정</span>
        </div>
        {cards_html}
    </main>
    <footer class="footer">
        <img src="logo.png" alt="HYUNDAI E&C" style="height:24px; margin-bottom:8px;">
        <p>HDEC AI 뉴스 큐레이션 · 건설업계 뉴스 종합 · {today_short} 자동 생성</p>
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
    print(f"  {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 1) 수집
    print("[1/6] 건설업계 뉴스 수집 중...")
    articles = collect_naver_news()
    print(f"  → 총 {len(articles)}건 수집")

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
        print(f"     [{i}] (점수:{art['_score']}, 화제성:{art.get('_hits',1)}) {art['title'][:50]}")

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
