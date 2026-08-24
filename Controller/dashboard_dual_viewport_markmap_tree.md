# 🌌🌿 대시보드 듀얼 뷰포트 (성단 네트워크 ↔ 접이식 마크다운 생각나무 마인드맵) 명세서

## 1. 개요 및 배경
Codex 및 고급 개발자 사용자는 복잡한 지식 네트워크를 다각도로 분석할 필요가 있습니다.
- **성단 네트워크 뷰 (`vis-network`)**: 노드 간의 물리력(Force-Directed)과 가중치(Weight) 엣지를 통해 연관 관계 허브와 클러스터를 한눈에 조망하기에 최적입니다.
- **접이식 마크다운 생각나무 마인드맵 뷰 (`Markmap`)**: 각 도메인(Gmarket 쿠폰, GNB 툴팁, 여행네컷, 챌린지 피드 등)별로 지식을 Root ➔ Branch ➔ Leaf 계층형 접이식 마인드맵으로 펼쳐보며, 문제 요구사항(Problem)과 실제 적용 해결책(Solution)의 논리적 흐름을 빠르게 정독하기에 최적입니다.

본 명세서는 전체화면 확대 모달(`#expandedGraphModal`) 내에 **`[🌌 성단 네트워크]` ↔ `[🌿 생각나무 마인드맵]` 원클릭 듀얼 뷰포트 전환 UX**를 구축하는 규격을 정의합니다.

---

## 2. UI/UX 아키텍처 및 화면 구성

```
┌────────────────────────────────────── 전체화면 모달 (#expandedGraphModal) ──────────────────────────────────────┐
│ [헤더 툴바]                                                                                                    │
│  • 뷰 모드 세그먼트: [ 🌌 성단 네트워크 (Active) ] [ 🌿 생각나무 마인드맵 ]                                    │
│  • 네트워크 전용 컨트롤 (물리엔진, 티어 필터, 화면맞춤)                                                         │
│  • 마인드맵 전용 컨트롤 (모두 펼치기, 모두 접기, 줌 리셋)                                                       │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [뷰포트 컨테이너]                                                                                              │
│                                                                                                                 │
│   (Mode 1: Network)  #expandedMemoryGraphCanvas (vis-network 물리 캔버스)                                       │
│   (Mode 2: Mindmap)  #expandedMarkmapContainer (#markmapSvg 접이식 SVG 캔버스)                                  │
│                                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 생각나무 마인드맵 (`Markmap`) 계층형 데이터 생성 규칙 및 상세 확인 링크

기억 저장소의 지식 에피소드를 구조화된 마크다운 트리로 자동 변환하며, 각 지식 노드 제목 및 메타 라인에 **원클릭 상세 확인 인터랙티브 링크(`<a class="tb-node-link" onclick="openNodeDetail(...)">...</a>`)**를 삽입합니다:

```markdown
# 🌿 TierBridge Thought-Tree (34 Pure Fruits)
## 🎫 쿠폰 및 결제 동기화 (MGTT-25938)
### 📌 #d48fb397 P1 쿠폰 사전 계산 금액 복원 및 XML NPE 방어 <a class="tb-node-link" onclick="openNodeDetail('d48fb397-...')">🔍 상세 확인</a>
- 💡 **적용 해결책**: `aplAmt` 복원 및 `GmarketGetCoupon` null 안전성 보강
- 🏷️ **메타**: 등급 [BRONZE] | LOC: 0줄 | 비용: $0.0416 | <a class="tb-node-link" onclick="openNodeDetail('d48fb397-...')">📖 전체 에피소드 & 소각 관리</a>
### 📌 #e8f0cab6 Gmarket 쿠폰 XML 연동 코드 리뷰 <a class="tb-node-link" onclick="openNodeDetail('e8f0cab6-...')">🔍 상세 확인</a>
- 💡 **적용 해결책**: `usedCupnAmt` vs `CouponType` 매핑 불일치 분석 및 예외 방어 리뷰
- 🏷️ **메타**: 등급 [BRONZE] | 가중치: 1.97x | <a class="tb-node-link" onclick="openNodeDetail('e8f0cab6-...')">📖 전체 에피소드 & 소각 관리</a>
...
```

---

## 4. 라이브러리 로딩 및 인터랙션 스펙

1. **CDN 의존성**:
   - `https://cdn.jsdelivr.net/npm/d3@7`
   - `https://cdn.jsdelivr.net/npm/markmap-view@0.15.4`
   - `https://cdn.jsdelivr.net/npm/markmap-lib@0.15.4`
2. **반응형 테마 및 클릭 액션**:
   - 다크 모드 / 라이트 모드에 맞춰 SVG 텍스트 및 링크 뱃지(`.tb-node-link`) 색상이 자동으로 전환됩니다.
   - 링크 클릭 시 `openNodeDetail(nodeId)`가 호출되어 해당 에피소드의 전체 문제/해결책 전문, 파일 경로, 세션 메타 및 **⚡ Neuralizer 소각 버튼**이 포함된 상세 모달이 즉시 열립니다.
3. **노드 인터랙션**:
   - 각 브랜치의 원형 버튼 클릭 시 하위 가지 접기/펼치기.
   - 마우스 휠 줌 및 드래그 팬(Pan) 완벽 지원.
