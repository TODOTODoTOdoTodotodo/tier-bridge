# Dashboard Fractal UI Theme Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
본 문서는 TierBridge 웹 대시보드(`usage_dashboard.html` 및 `analyze_usage.py`)의 UI/UX 디자인을 **HTML5 UP Fractal**(`https://html5up.net/fractal`) 디자인 랭귀지 기반으로 전면 리뉴얼하기 위한 아키텍처 및 구현 규격서입니다.

과도한 미사여구와 과장된 사이파이(Sci-Fi) 스타일의 텍스트/스타일을 걷어내고, Fractal 템플릿의 핵심 시그니처인 **산뜻하고 가벼운 스카이블루-화이트 듀오톤, 원형 아이콘 스포트라이트 뱃지, 모던 필(Pill)/아웃라인 액션 버튼, 통일된 타이포그래피**를 도입하여 가독성과 직관성을 극대화합니다.

---

## 2. 디자인 DNA 분석 (HTML5 UP Fractal Design DNA)

### 2.1 색상 체계 (Color Palette)
- **Primary Accent (Fractal Blue)**: `#4696e5`
- **Primary Gradient**: `linear-gradient(135deg, #4696e5 0%, #3089e2 100%)`
- **Header Text**: White `#ffffff` (주요 타이틀), `#d1e5f9` (부제목 및 라벨)
- **Light Mode Body**: `#f7f9fc` (소프트 쿨 그레이 배경), 카드 컨테이너 `#ffffff`
- **Dark Mode Body (Fractal Slate Dark)**: `#151821` (정제된 슬레이트 다크), 카드 컨테이너 `#1c212d`
- **Borders & Dividers**: `1px solid #e2e8f0` (라이트) / `1px solid rgba(255, 255, 255, 0.08)` (다크)

### 2.2 핵심 UI 컴포넌트 규격
1. **시그니처 히어로 헤더 (`.fractal-header`)**:
   - Fractal 고유의 `#4696e5` 그라데이션 및 부드러운 래디얼 오버레이 적용.
   - 원형 아이콘 프레임(`fractal-icon-circle lg`, 반투명 화이트 배경 및 보더)과 깔끔한 서비스명(`TierBridge`), 간결한 서브타이틀(`AI 사용량 및 모델 라우팅 현황`) 배치.
   - 우측 툴바에는 화이트/반투명 글래스 형태의 드롭다운(월, 세션, 버전 선택)과 라이브 갱신 툴바, 화이트 솔리드(Primary) 및 반투명 아웃라인(Alt) 액션 버튼 배치.

2. **원형 아이콘 스포트라이트 (`.fractal-icon-circle`)**:
   - HTML5 UP Fractal Section 1/2의 시그니처인 `icon major` 원형 아이콘 프레임 구현.
   - 각 KPI 지표(크레딧, 비용, 토큰, 세션, 절감액) 및 텔레메트리 카드에 고유 컬러 원형 뱃지 적용.

3. **세그먼트 탭 내비게이션 (`#tabNavigation`)**:
   - 군더더기 없는 모던 필 탭 바. 활성 탭에 `#4696e5` 배경 및 화이트 텍스트, 그림자 적용.

4. **깔끔한 카드 및 테이블 레이아웃**:
   - 불필요한 네온 글로우 제거, 은은하고 정갈한 드롭섀도우(`0 2px 8px rgba(0,0,0,0.03)`).
   - 테이블 헤더에 가독성 높은 그레이 톤 및 대문자 트래킹 적용, 행별 미세 교차 스트라이프 및 호버 하이라이트.

5. **테마 기본값 (Theme Policy)**:
   - Fractal 본연의 시그니처 룩앤필을 전달하기 위해 기본 테마는 `light`로 설정하며, 브라우저 로컬 스토리지(`tb_theme`)를 존중함.

---

## 3. 구현 세부 규격 (Implementation Details)

### 3.1 `analyze_usage.py` 스타일 및 마크업 수정
- CSS 루트 변수 정의: `--fractal-blue: #4696e5;`, `--fractal-blue-dark: #3089e2;`, `--fractal-subtext: #d1e5f9;`.
- 구형 사이파이 네온 다크 스타일을 Fractal Light & Slate Dark 반응형 스타일로 교체.
- 히어로 헤더 마크업을 `.fractal-header` 구조로 전면 리팩토링.
- 5대 KPI 카드에 `.fractal-icon-circle` 적용 및 폰트 굵기/여백 정돈.
- 자바스크립트 `applyTheme` 함수 내 차트 눈금선 및 텍스트 컬러 동적 업데이트 로직 강화.

### 3.2 배포 및 검증 규격
- `deploy.sh` 실행을 통한 라이브 런타임(`~/.tierbridge/live`) 동기화 및 서비스 정상 기동(Port 18080) 확인.
- 브라우저 및 정적 HTML 렌더링 확인.
