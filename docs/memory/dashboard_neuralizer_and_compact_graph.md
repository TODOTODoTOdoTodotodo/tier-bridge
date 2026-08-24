# 📑 [설계 명세서] Neuralizer(기억 소각) 연동 & 콤팩트/확대 듀얼 생각나무 그래프 UX

본 문서는 특정 오염 기억 노드를 안전하게 삭제하는 **`Neuralizer` 기능 연동**과, 검색 영역 우측에 미니 캔버스를 기본 배치하고 필요 시 전체화면으로 확장하는 **콤팩트/확대 듀얼 생각나무 그래프 UX** 설계 명세서입니다.

---

## 1. 📌 설계 목표 및 핵심 요구사항

1. **⚡ Neuralizer (기억 정밀 소각) 파이프라인**:
   - `nodes` 테이블에서 대상 노드 삭제 (`DELETE FROM nodes WHERE id = ?`)
   - `edges` 테이블에서 연관 연결선 일괄 정리 (`DELETE FROM edges WHERE source_id = ? OR target_id = ?`)
   - 대시보드 모달 및 테이블에서 원클릭 소각 후 대시보드 실시간 자동 갱신.
2. **📱 2단 분할 레이아웃 (Side-by-Side Compact Mini Graph)**:
   - **좌측 (60%)**: 연관 기억 시맨틱 검색기 & 유사도 랭킹 결과 카드 스트림.
   - **우측 (40%)**: 검색 및 선택 노드 중심의 **콤팩트 생각나무 미니 캔버스** (`height: 380px`).
   - 검색 결과 카드를 클릭하면 우측 미니 그래프의 해당 노드로 카메라가 자동 포커스 줌인.
3. **⛶ 전체 화면 확대 모달 (Fullscreen Expanded Graph)**:
   - 미니 캔버스 상단의 `[⛶ 전체 화면 확대]` 버튼 클릭 시, 화면 전체(Full Screen Viewport)를 사용하는 대형 인터랙티브 캔버스로 확장.
   - 물리 엔진 토글, 티어 필터, 1-hop 연관 가지 하이라이팅 등 전문 탐색 도구 제공.
4. **🎯 핸들링 편의성 고도화**:
   - 노드 클릭 시 연관된 1-hop/2-hop 엣지만 선명하게 강조(Highlight)하고 무관 노드는 Fade-out.
   - 부드러운 카메라 이동 (`network.focus(nodeId, {scale: 1.25, animation: {duration: 600}})`).

---

## 2. 🏗️ 아키텍처 및 API 규격

```
[UI: Neuralizer 버튼 클릭] ──► [POST /v1/dashboard/memories/neuralize/{id}]
                                         │
                                         ▼
                            [MemoryHandler.neuralize_memory(id)]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
      [DELETE FROM nodes WHERE id=?]             [DELETE FROM edges WHERE ...]
```

* **API 엔드포인트 (`harness.py`)**:
  * `POST /v1/dashboard/memories/neuralize/{node_id}`
  * **Response**: `{"status": "deleted", "node_id": "...", "deleted_edges_count": 3}`
