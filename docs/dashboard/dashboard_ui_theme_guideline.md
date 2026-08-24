# 📑 [설계 명세서] TierBridge 대시보드 모던 세그먼트 탭 & 3종 테마(다크/라이트/시스템) 전환 시스템

본 문서는 TierBridge 웹 대시보드(`usage_dashboard.html` / `analyze_usage.py`)의 탭 네비게이션 UI를 최신 웹 프론트엔드 표준(Vercel/Shadcn/Tailwind UI 세그먼트 컨트롤)으로 고도화하고, 3종 테마(어두운/밝은/기본-시스템) 전환 및 영속 저장 기능을 제공하기 위한 **UI/UX 설계 명세서**입니다.

---

## 1. 📌 설계 목표 및 주요 요구사항

1. **현대적 세그먼트 탭 네비게이션 (Segmented Control Bar)**:
   - 플랫한 단순 버튼 나열을 지양하고, 일체형 캡슐(Pill Container) 내부에 슬라이딩 및 글래스모피즘 그라데이션이 적용된 프리미엄 탭 바 구축.
   - 각 탭에 활성 상태를 나타내는 직관적인 아이콘, 서브텍스트, 실시간 배지 카운터 결합.
2. **3종 테마 전환 엔진 (Theme Switching Engine)**:
   - 🌙 **어두운 모드 (Dark - Midnight Slate)**: OLED 친화적 다크 글래스모피즘 (`#0b0f19`).
   - ☀️ **밝은 모드 (Light - Pure Minimal Slate)**: 고대비 및 눈의 피로도를 낮춘 미니멀 화이트 (`#f8fafc` / `#ffffff`).
   - 💻 **기본/시스템 모드 (System / OS Default)**: 브라우저 및 OS `prefers-color-scheme` 선호도를 실시간 자동 감지.
3. **영속성 및 반응형 동기화**:
   - `localStorage`(`tierbridge_theme`)에 사용자 선호 테마를 자동 저장하여 브라우저 새로고침이나 3초 라이브 폴링 중에도 테마 상태 완벽 보존.
   - `Chart.js` 및 `vis-network` 그래프의 텍스트, 그리드, 엣지 컬러를 테마 모드에 맞게 동적 재조정.

---

## 2. 🎨 UI/UX 컴포넌트 세부 명세

### 2.1 세그먼트 탭 컨트롤 (Segmented Pill Bar)
```html
<div class="inline-flex p-1.5 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-inner backdrop-blur-md gap-1.5">
    <button id="tabBtnUsage" onclick="switchDashboardTab('usage')" class="...">
        <i class="fa-solid fa-chart-line"></i>
        <span>AI 사용량 & 크레딧 관제</span>
    </button>
    <button id="tabBtnMemory" onclick="switchDashboardTab('memory')" class="...">
        <i class="fa-solid fa-brain"></i>
        <span>Giyeok 장기 기억저장소 & 생각나무</span>
        <span id="memTabCountBadge">48건</span>
    </button>
</div>
```

### 2.2 테마 전환 컨트롤러 (Theme Switcher Widget)
* 헤더 우측 상단에 3-Segment 테마 선택 버튼 배치:
  * `[ 🌙 다크 | ☀️ 라이트 | 💻 시스템 ]`
* **동작 원리**:
  - `html` 태그의 `class`를 `dark` 또는 `light`로 동적 전환.
  - CSS 커스텀 스타일링을 통해 0ms 지연으로 전체 UI 테마 일괄 전환.

---

## 3. 🧪 검증 시나리오

1. **탭 전환 검증**: 사용량 관제 ↔ 기억저장소 탭 간 부드러운 전환 및 그래프/테이블 렌더링 유지.
2. **테마 전환 검증**: 다크 ➔ 라이트 ➔ 시스템 전환 시 카드 배경, 폰트 색상, 테이블 가독성 및 차트/그래프 캔버스 색상 동기화 확인.
3. **새로고침 유지 검증**: F5 새로고침 후에도 이전에 선택한 테마와 탭이 그대로 복원되는지 확인.
