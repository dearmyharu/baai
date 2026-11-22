"""사전: 질문 속 말 → 데이터의 실제 값. 여기 있는 말만 조건으로 통과한다(닫힌 사전).

- AI가 고른 조건은 '근거 표현'(질문 속 단어)이 이 사전의 동의어여야 통과한다.
  예: '인스타' → KAKAO 는 '인스타'가 KAKAO의 동의어가 아니라서 막힌다.
- NOT_IN_DATA: 데이터에 없는 항목. 질문에 있으면 AI를 부르지 않고 정해진 안내를 낸다.
"""
from __future__ import annotations

import re

# 카테고리 이름(실제) → 질문에서 쓰는 말. 실제 이름의 각 부분(·로 나뉜 말)은 자동으로 포함된다.
CATEGORY_WORDS = {
    "정육": ["고기", "육류", "소고기", "돼지고기", "닭고기", "한우", "한돈"],
    "수산": ["생선", "해산물", "수산물"],
    "채소·과일": ["야채", "청과"],
    "음료·커피": ["음료수", "커피류"],
    "유제품·계란": ["우유", "달걀", "치즈", "요거트"],
    "쌀·잡곡·면": ["곡물", "국수", "라면"],
    "반찬·김치": [],
    "캠핑·바비큐": ["바베큐", "BBQ"],
    "샐러드·건강식": ["건강 식품"],
    "베이커리·브런치": ["빵", "제과"],
    "양념·소스": ["조미료", "양념류"],
    "과자·간식": ["스낵", "디저트"],
    "냉동식품": ["냉동"],
    "간편식": ["즉석식품", "HMR"],
    "밀키트": ["밀 키트"],
}

# 고객 조건: 키 → {실제 값: [질문 속 말]}
FILTER_WORDS = {
    "gender": {"F": ["여성", "여자", "여성 고객"], "M": ["남성", "남자", "남성 고객"]},
    "age_groups": {"10대 이하": ["10대", "10대 이하", "십대"], "20대": ["20대"], "30대": ["30대"], "40대": ["40대"],
                   "50대": ["50대"], "60대 이상": ["60대", "60대 이상", "시니어"]},
    "signup_channels": {"KAKAO": ["카카오", "kakao", "카톡"], "NAVER": ["네이버", "naver"], "GOOGLE": ["구글", "google"],
                        "EMAIL": ["이메일", "email", "메일"], "DIRECT": ["직접 가입", "일반 가입", "자체 가입"]},
    "grades": {"VIP": ["vip"], "GOLD": ["골드", "gold"], "SILVER": ["실버", "silver"], "BRONZE": ["브론즈", "bronze"]},
    "customer_type": {"첫 구매": ["첫 구매", "첫구매", "처음 산", "처음 구매", "신규 구매"],
                      "기존 구매": ["기존 고객", "기존 구매", "재구매 고객", "단골"]},
    "new_signup": {True: ["신규 가입", "새로 가입", "갓 가입", "신규 회원"]},
}
REGION_WORDS = {  # 실제 이름 → 줄임말
    "서울특별시": ["서울"], "부산광역시": ["부산"], "대구광역시": ["대구"], "인천광역시": ["인천"], "광주광역시": ["광주"],
    "대전광역시": ["대전"], "울산광역시": ["울산"], "세종특별자치시": ["세종"], "경기도": ["경기"], "강원특별자치도": ["강원"],
    "충청북도": ["충북"], "충청남도": ["충남"], "전북특별자치도": ["전북"], "전라남도": ["전남"], "경상북도": ["경북"],
    "경상남도": ["경남"], "제주특별자치도": ["제주"],
}
FILTER_WORDS["regions"] = {k: [k] + v for k, v in REGION_WORDS.items()}

# 변화 위치 축: 키 → 질문 속 말 (근거가 없으면 축은 기본값으로 정한다)
AXIS_WORDS = {   # 구분 '이름'만 (서울·카카오 같은 값은 고객 조건이지 나눠 보기가 아니다)
    "category": ["카테고리", "분야", "부문"],
    "product": ["상품", "제품", "품목"],
    "customer_type": ["고객별", "고객 유형", "고객 구분", "첫 구매", "첫구매", "기존 고객", "신규 고객", "재구매"],
    "visitor_type": ["신규 방문", "재방문", "방문 구분", "방문자"],
    "path": ["경로별", "쇼핑몰 안 경로", "큐레이션 경유", "일반 탐색"],
    "weekday": ["요일"],
    "daypart": ["시간대", "몇 시", "시간별"],
    "gender": ["성별", "남녀"],
    "age_group": ["연령", "나이", "연령대"],
    "region": ["지역", "시도", "시·도"],
    "signup_channel": ["가입 수단", "가입 경로", "가입 방법", "가입 채널"],
    "grade_at_order": ["등급"],
}

# 데이터에 없는 항목: 이름 → (질문 속 말 정규식, 대신 볼 수 있는 것)
NOT_IN_DATA = {
    "광고·외부 유입 경로": (r"인스타|instagram|페북|페이스북|facebook|유튜브|youtube|틱톡|tiktok|트위터|(?<![a-z])sns(?![a-z])|"
                      r"블로그|바이럴|인플루언서|광고(?!\s*없이)|(?<![a-z])(?:ads?|cpc|cpm|ctr|roas|utm)(?![a-z])|"
                      r"유입\s*(?:경로|채널|출처)|어디서\s*(?:들어|왔|유입|알고)|"
                      r"(?:네이버|구글|다음|카카오)\s*(?:검색|쇼핑|광고|블로그|카페)\s*(?:으로|로|에서|통해|타고|보고)",
                      "회원가입 수단(카카오·네이버 등 어떤 계정으로 가입했는지)은 볼 수 있지만, 유입 경로는 아닙니다."),
    "추천인·초대·제휴": (r"추천인|지인\s*추천|친구\s*(?:추천|초대)|초대\s*(?:코드|이벤트)|제휴", ""),
    "체류 시간": (r"체류\s*시간|머문\s*시간|머무는\s*시간|스크롤", "상품 클릭 후 장바구니·구매로 이어진 비율은 볼 수 있습니다."),
    "결제 페이지": (r"결제\s*(?:페이지|화면|단계|창)|결제\s*이탈", "장바구니 담기 후 구매로 이어진 비율은 볼 수 있습니다."),
    "접속 기기": (r"모바일|(?<![a-z])pc(?![a-z])|앱\s*(?:에서|으로|사용자)|데스크톱|기기|디바이스|ios|안드로이드|android",
              "요일·시간대별 주문은 볼 수 있습니다."),
    "리뷰·문의": (r"리뷰|후기|별점|평점|고객\s*문의|고객\s*센터|클레임", "취소·환불은 볼 수 있습니다."),
    "재고": (r"재고|품절|입고\s*(?:일|량|예정|지연)", "상품별 판매 수량은 볼 수 있습니다."),
    "경쟁사": (r"경쟁사|경쟁\s*업체|타사|다른\s*쇼핑몰|쿠팡|마켓컬리|컬리|이마트몰", "이 쇼핑몰의 가격 변경 이력은 볼 수 있습니다."),
    "비회원": (r"비회원|로그인\s*(?:안\s*한|하지\s*않은)", "신규 가입 고객과 기존 고객은 나눠 볼 수 있습니다."),
    "날씨·외부 요인": (r"날씨|기온|비가\s*와|비\s*와서|더워서|추워서|명절", ""),
}
for _k, (_p, _alt) in list(NOT_IN_DATA.items()):
    NOT_IN_DATA[_k] = (re.compile(_p, re.I), _alt)

REPHRASE_EXAMPLES = "예: '30대 여성이 많이 사는 카테고리는?', '서울 고객 정육 매출은?', '첫 구매 고객 매출은?'"


def rephrase(word: str) -> str:
    """데이터에 없는 집단·조건을 물었을 때: 추측해서 바꾸지 않고 다시 묻게 한다."""
    return (f"'{word}'은(는) 이 데이터에 없는 구분이라, 비슷한 조건으로 바꿔 계산하지 않았습니다. "
            f"데이터에 있는 조건으로 다시 질문해 주십시오. 있는 조건: {HAVE_IN_DATA}. {REPHRASE_EXAMPLES}")


HAVE_IN_DATA = "성별·연령대·지역·회원가입 수단·회원 등급·첫 구매/기존 고객·신규 가입, 카테고리·상품, 쇼핑몰 안 경로(큐레이션/일반 탐색), 요일·시간대"

# 일반어: 상품 이름을 찾을 때 근거에서 뺀다
STOP_WORDS = {"매출", "상품", "제품", "품목", "어때", "어때요", "얼마", "얼마야", "보여줘", "알려줘", "1위", "1등", "top",
              "탑", "베스트", "최고", "상위", "하위", "꼴찌", "순위", "제일",
              "가장", "많이", "잘", "팔리는", "팔린", "판매", "주문", "수량", "이익", "이익률", "추이", "최근", "지난주",
              "어제", "요즘", "카테고리", "쪽", "중", "중에서", "에서", "은", "는", "이", "가", "을", "를", "의"}
# '데이터에 없음'으로 인정하지 않는 말 (사전에 있는 말: 지표·구매 단계·시점)
KNOWN_TERMS = ["매출", "주문", "판매", "이익", "객단가", "수량", "전환", "장바구니", "구매", "클릭", "방문", "세션", "단계",
               "테마", "큐레이션", "프로모션", "할인", "쿠폰", "무료배송", "배송비", "순위", "비중", "추이", "지난번", "저번",
               "예전", "요즘", "최근", "평소"]

# 질문 말투(의문사·서술어 조각): '데이터에 없음' 항목에서 빼고 판단한다
GENERIC_RE = re.compile(r"^(?:왜|어떻게|어때|어떤|어떰|지금|현재|요즘|좀|진짜|결과|상황|얼마나|얼마|뭐|무슨|언제)$|"
                        r"(?:었어|았어|졌어|었나|았나|있어|있나|되고|되어|됐어|해|돼|나요|니|까|야|지|요|음|줘|줘요|봐|봐줘|고|서|면|는데|니까|나서)$")


def generic_only(text: str) -> bool:
    """의문사·서술어 조각만으로 된 말이면 True (예: '왜 늘었어', '지금, 어떻게 되고 있어?')."""
    toks = [t for t in re.split(r"[\s,?!.]+", text or "") if t]
    return all(GENERIC_RE.search(t) for t in toks)


# 이어지는 질문의 형태: '그럼 수산은?', '고객별로는?', '지난주는?' 처럼 짧거나 이어 말하는 말로 시작
FOLLOW_RE = re.compile(r"^\s*(?:그럼|그러면|그건|그거|거기|이번엔|이건|저건|그 중|그중)|^\S{1,8}(?:은|는|도|로는|별로는|만)\??\s*$")

WHY_RE = re.compile(r"왜|이유|원인|때문|어째서|뭣\s*때문")


def norm(s: str) -> str:
    """비교용: 소문자, 공백 제거."""
    return re.sub(r"\s+", "", (s or "").lower())


def category_words(cat: str) -> list[str]:
    return [cat] + [p for p in cat.split("·") if p] + CATEGORY_WORDS.get(cat, [])


def words_match(evidence: str, words: list[str]) -> bool:
    """근거 표현이 사전 말 중 하나를 포함하는지(공백 무시). 정규식 말(\\d 포함)도 허용."""
    e = norm(evidence)
    for w in words:
        if "\\" in w:
            if re.search(w, e):
                return True
        elif norm(w) and norm(w) in e:
            return True
    return False


def known_term(text: str, categories: list[str]) -> bool:
    """사전에 있는 말(카테고리·고객 조건·구분 이름·지표·시점)이 들어 있으면 True."""
    words = list(KNOWN_TERMS) + [w for c in categories for w in category_words(c)]
    words += [w for vals in FILTER_WORDS.values() for ws in vals.values() for w in ws]
    words += [w for ws in AXIS_WORDS.values() for w in ws]
    return words_match(text, words)


def product_tokens(names: list[str], categories: list[str]) -> set[str]:
    """상품 이름을 이루는 단어 중 상품을 가리킬 수 있는 것(규격·맛·카테고리 말 제외)."""
    cat_words = {norm(w) for c in categories for w in category_words(c)}
    out = set()
    for n in names:
        for t in re.split(r"[\s()/]+", n):
            t = norm(t)
            if len(t) >= 2 and t not in cat_words and not re.search(r"\d|개입|입$|맛$|형$|용$", t) and t not in STOP_WORDS:
                out.add(t)
    return out


def category_in(question: str, categories: list[str]) -> str | None:
    """질문에 카테고리 말이 하나의 카테고리만 가리키면 그 카테고리 (AI가 카테고리를 비웠을 때)."""
    hits = [c for c in categories if words_match(question, category_words(c))]
    return hits[0] if len(hits) == 1 else None


def axis_in(question: str) -> str | None:
    """질문에 구분 이름이 하나만 있으면 그 축 (AI가 축을 비웠을 때 코드가 찾는다)."""
    hits = [k for k, ws in AXIS_WORDS.items() if k not in ("category", "product") and words_match(question, ws)]
    return hits[0] if len(hits) == 1 else None


def not_in_data(question: str) -> tuple[str, str] | None:
    """질문에 데이터에 없는 항목이 있으면 (이름, 대신 볼 수 있는 것)."""
    for name, (rx, alt) in NOT_IN_DATA.items():
        if rx.search(question or ""):
            return name, alt
    return None
