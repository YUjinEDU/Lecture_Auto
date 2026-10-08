# S21 Audio Quality — 자연스럽고 노이즈 없는 고품질 강의 음성 달성 계획

## 1. 개요 및 목적
- **목표**: 교수님이 지적하신 음성의 늘어짐, 어눌함, 이상한 노이즈(쇳소리, 기계음, 잔향)를 제거하여 "자연스럽고 깨끗한 스튜디오 강의 음성" 달성.
- **원칙**:
  1. 기저 모델(KRAFTON/Raon-Speech-9B)은 유지하되, 참조 음성·디코딩 파라미터·신호처리 마스터링 체인을 고도화.
  2. 기존 S0~S20 안전장치 및 결정성(Determinism) 훼손 금지.
  3. 에이전트 간 토론과 엄밀한 리서치에 기반하여 가설을 세우고, 청취 실험으로 증명.

## 2. 핵심 쟁점 및 에이전트 토론
- `DEBATE_AND_RESEARCH.md` 참조 (진행 중)

## 3. 작업 로드맵
- Phase 1: 참조 음성(Reference Audio) 스튜디오 클리닝 (노이즈/룸 잔향 제거)
- Phase 2: 디코딩 파라미터(Temperature/Sampling/EOS Tail Trim) 튜닝
- Phase 3: 경량 오디오 DSP 마스터링 체인 (De-esser, High-pass, Leveler)
- Phase 4: A/B 비교 청취 평가 및 회귀 검증
