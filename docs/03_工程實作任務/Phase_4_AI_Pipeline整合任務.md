# Phase 4：AI Pipeline 整合任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

把 Phase 1 的本地 pipeline 封裝成 worker 可呼叫、可替換模型 adapter、可寫 artifact metadata 的正式 AI pipeline service。

## 前置條件

- Phase 1 本地 runner 可跑通。
- Phase 2 StorageAdapter 與資料模型可用。
- Phase 3 worker orchestration 可用 mock pipeline 跑通。

## 需參考的 Level 1 / Level 2 文件

- Level 1：AI音訊處理流程.md
- Level 1：系統架構.md
- Level 2：AI_Pipeline執行規格.md
- Level 2：Demucs鼓軌分離規格.md
- Level 2：ADTOF鼓MIDI轉寫規格.md
- Level 2：檔案儲存與Artifact規格.md

## 任務清單

- `GS-P4-001`：後段整合票：將 Phase 1 pipeline 封裝成 worker service
- `GS-P4-002`：建立 SourceSeparator interface
- `GS-P4-003`：建立 DemucsSourceSeparator adapter
- `GS-P4-004`：建立 DrumTranscriber interface
- `GS-P4-005`：建立 AdtofDrumTranscriber adapter
- `GS-P4-006`：建立 artifact metadata 寫入流程
- `GS-P4-007`：建立 pipeline error mapping
- `GS-P4-008`：建立模型版本與 pipeline version 記錄
- `GS-P4-009`：建立 AudioPreprocessor interface / ffmpeg adapter 正式化
- `GS-P4-010`：建立 MidiPostProcessor service 正式化
- `GS-P4-011`：建立 NotationGenerator / PdfExporter interface 與 worker integration

## Ticket 詳細內容

### GS-P4-001 — 後段整合票：將 Phase 1 pipeline 封裝成 worker service

**Ticket ID**
GS-P4-001

**Ticket 名稱**
後段整合票：將 Phase 1 pipeline 封裝成 worker service

**背景與目的**
這張 ticket 是 Phase 4 後段整合票，不應照票號第一個開工。目的，是在各 interface / adapter / stage service 完成後，把本地 runner 轉成正式 `PipelineService`，並讓 worker 可呼叫端到端 pipeline。

**實作範圍**
- 建立 `PipelineService.run(job_id, config)`。
- 從 storage 取 original artifact 到 temp dir。
- 串接 AudioPreprocessor、SourceSeparator、DrumTranscriber、MidiPostProcessor、NotationGenerator、PdfExporter。
- 回傳 artifacts、summary、warnings 與 stage reports。

**不包含範圍**
- 不把 service 綁死 Celery。
- 不在 API 層呼叫。

**主要修改位置或建議目錄**
- ai_pipeline/service.py
- worker/app/pipeline_runner.py

**輸入**
- job_id、ArtifactRef、pipeline config。

**輸出**
- PipelineResult。
- artifacts。

**API / Data Model / Storage 關聯**
- Data：DrumTrack、ExportFile 由後續 ticket 寫入；Storage：全階段 artifacts。

**驗收標準**
- `PipelineService` 可被 worker 與 tests 直接呼叫。
- `PipelineService` 不依賴 FastAPI request / response。
- 已串接 AudioPreprocessor、SourceSeparator、DrumTranscriber、MidiPostProcessor、NotationGenerator、PdfExporter。
- 可用 mock adapters 跑完端到端 orchestration。
- 文件明確標註此票需在 Phase 4 主要 interface / adapter / stage tickets 完成後再做。

**測試要求**
- service test with mock adapters。

**相依任務**
GS-P1-007, GS-P3-004, GS-P2-005, GS-P4-002, GS-P4-003, GS-P4-004, GS-P4-005, GS-P4-009, GS-P4-010, GS-P4-011, GS-P4-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-002 — 建立 SourceSeparator interface

**Ticket ID**
GS-P4-002

**Ticket 名稱**
建立 SourceSeparator interface

**背景與目的**
定義 source separation 模型抽象，讓 Demucs 可替換。

**實作範圍**
- 定義 `SourceSeparator.separate(input_audio, config) -> StemSet`。
- 定義 StemSet 與 SourceSeparationResult。
- 定義錯誤型別與 validation contract。

**不包含範圍**
- 不實作 Demucs。
- 不做多模型 routing。

**主要修改位置或建議目錄**
- ai_pipeline/contracts/source_separator.py
- ai_pipeline/source_separation/

**輸入**
- normalized audio ArtifactRef 或 temp path。

**輸出**
- StemSet。

**API / Data Model / Storage 關聯**
- Storage：輸出 drums stem key 由 adapter 或 service 寫入。

**驗收標準**
- interface 可被 mock。
- service 不依賴 Demucs class。

**測試要求**
- contract unit test。

**相依任務**
GS-P1-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-003 — 建立 DemucsSourceSeparator adapter

**Ticket ID**
GS-P4-003

**Ticket 名稱**
建立 DemucsSourceSeparator adapter

**背景與目的**
實作 SourceSeparator 的 Demucs adapter，接入正式 pipeline。

**實作範圍**
- 包裝 Demucs CLI 或 Python API。
- 處理 temp directory、model name、device、timeout。
- 輸出 drums.wav 並 validation。
- 轉換 Demucs 錯誤為 domain error。

**不包含範圍**
- 不保存其他 stems。
- 不加入替代 separator。

**主要修改位置或建議目錄**
- ai_pipeline/source_separation/demucs_adapter.py

**輸入**
- normalized.wav。
- Demucs config。

**輸出**
- drums.wav artifact。
- source separation report。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob.source_separator/version、DrumTrack.drums_stem_storage_key；Storage：`jobs/{job_id}/stems/drums.wav`。

**驗收標準**
- pipeline 可用 Demucs adapter 產生 drums stem。
- Demucs 失敗時 job failed。

**測試要求**
- mock command test。
- slow integration test 短音檔。

**相依任務**
GS-P4-002, GS-P1-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-004 — 建立 DrumTranscriber interface

**Ticket ID**
GS-P4-004

**Ticket 名稱**
建立 DrumTranscriber interface

**背景與目的**
定義 drum transcription 模型抽象，讓 ADTOF 與未來 Omnizart 可替換。

**實作範圍**
- 定義 `DrumTranscriber.transcribe(drums_audio, config) -> TranscriptionResult`。
- 定義 raw MIDI artifact、event count、warnings、model metadata。
- 定義空 MIDI / invalid MIDI contract。

**不包含範圍**
- 不實作 ADTOF。
- 不做 fallback。

**主要修改位置或建議目錄**
- ai_pipeline/contracts/drum_transcriber.py
- ai_pipeline/transcription/

**輸入**
- drums audio ArtifactRef 或 temp path。

**輸出**
- TranscriptionResult。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob.drum_transcriber/version、DrumTrack.raw_midi_storage_key。

**驗收標準**
- interface 可被 mock。
- pipeline service 不依賴 ADTOF 實作。

**測試要求**
- contract unit test。

**相依任務**
GS-P1-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-005 — 建立 AdtofDrumTranscriber adapter

**Ticket ID**
GS-P4-005

**Ticket 名稱**
建立 AdtofDrumTranscriber adapter

**背景與目的**
實作 DrumTranscriber 的 ADTOF-pytorch adapter。

**實作範圍**
- 包裝 ADTOF-pytorch CLI 或 Python API。
- 處理 checkpoint、device、threshold、timeout。
- 輸出 raw_drum.mid。
- 驗證 MIDI 可 parse 與 event count。

**不包含範圍**
- 不實作 Omnizart fallback。
- 不暴露 threshold 給使用者。

**主要修改位置或建議目錄**
- ai_pipeline/transcription/adtof_adapter.py

**輸入**
- drums.wav。
- ADTOF config。

**輸出**
- raw_drum.mid。
- transcription report。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob.drum_transcriber/version、DrumTrack.raw_midi_storage_key；Storage：`jobs/{job_id}/midi/raw_drum.mid`。

**驗收標準**
- 短 drums.wav 可產生 raw MIDI。
- 空 MIDI 有 warning 或 failed。

**測試要求**
- mock adapter test。
- slow integration test。

**相依任務**
GS-P4-004, GS-P1-004

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-006 — 建立 artifact metadata 寫入流程

**Ticket ID**
GS-P4-006

**Ticket 名稱**
建立 artifact metadata 寫入流程

**背景與目的**
讓 pipeline 每個 stage 的 artifact 都被保存並寫入對應 Data Model。

**實作範圍**
- 建立 artifact writer helper。
- 寫入 normalized、drums、raw_midi、processed_midi、drum_events、musicxml、pdf。
- 建立或更新 DrumTrack。
- 建立 ExportFile records。

**不包含範圍**
- 不做 S3 adapter 真實實作。
- 不做 artifact cleanup。

**主要修改位置或建議目錄**
- ai_pipeline/artifacts.py
- worker/app/pipeline_runner.py
- backend/app/models/

**輸入**
- ArtifactRef、job_id、stage。

**輸出**
- DrumTrack、ExportFile records。
- pipeline log artifact。

**API / Data Model / Storage 關聯**
- Data：AudioFile、DrumTrack、ExportFile；Storage：全部 MVP artifact keys。

**驗收標準**
- 每個 stage 完成後 DB 可查 artifact key。
- 下載 API 可根據 ExportFile 找到檔案。

**測試要求**
- integration test：mock pipeline 產生 artifacts 後 result API 可讀。

**相依任務**
GS-P4-001, GS-P4-003, GS-P4-005, GS-P4-009, GS-P4-010, GS-P4-011, GS-P2-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-007 — 建立 pipeline error mapping

**Ticket ID**
GS-P4-007

**Ticket 名稱**
建立 pipeline error mapping

**背景與目的**
將 ffmpeg、Demucs、ADTOF、MIDI、notation、PDF 錯誤映射為穩定錯誤碼。

**實作範圍**
- 定義 pipeline domain exceptions。
- 建立 stage error mapping。
- 接入 worker failed handling。
- 保留 internal_error_ref。

**不包含範圍**
- 不做錯誤管理後台。

**主要修改位置或建議目錄**
- ai_pipeline/errors.py
- worker/app/error_mapping.py

**輸入**
- exception、stage、context。

**輸出**
- error_code、user_message、retriable、internal log。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob.error_*；API：status failed response。

**驗收標準**
- 每個主要 stage 錯誤有對應 code。
- 不回傳 stack trace 給前端。

**測試要求**
- unit tests：exception to error response。
- worker test：adapter error → failed job。

**相依任務**
GS-P3-005, GS-P4-009, GS-P4-003, GS-P4-005, GS-P4-010, GS-P4-011

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-008 — 建立模型版本與 pipeline version 記錄

**Ticket ID**
GS-P4-008

**Ticket 名稱**
建立模型版本與 pipeline version 記錄

**背景與目的**
保存 pipeline、Demucs、ADTOF 版本資訊，讓日後比較準確度與 debug 有依據。

**實作範圍**
- 定義 pipeline_version。
- 讀取 adapter model name/version/checkpoint。
- 寫入 TranscriptionJob 對應欄位。
- 寫入 pipeline log。

**不包含範圍**
- 不建立模型 registry。
- 不做 A/B test UI。

**主要修改位置或建議目錄**
- ai_pipeline/versioning.py
- worker/app/pipeline_runner.py

**輸入**
- pipeline config、adapter metadata。

**輸出**
- TranscriptionJob version fields。
- pipeline log metadata。

**API / Data Model / Storage 關聯**
- Data：pipeline_version、source_separator_version、drum_transcriber_version。

**驗收標準**
- completed job 可查到版本資訊。
- mock adapter 也能提供 version。

**測試要求**
- unit test：version metadata。
- integration test：job completed 後欄位存在。

**相依任務**
GS-P4-003, GS-P4-005, GS-P4-006

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P4-009 — 建立 AudioPreprocessor interface / ffmpeg adapter 正式化

**Ticket ID**
GS-P4-009

**Ticket 名稱**
建立 AudioPreprocessor interface / ffmpeg adapter 正式化

**背景與目的**
Phase 1 已有 ffmpeg POC；本 ticket 將其正式化為可被 PipelineService 呼叫的 `AudioPreprocessor` interface 與 ffmpeg adapter，讓 preprocessing stage 有清楚邊界與錯誤映射。

**實作範圍**
- 定義 `AudioPreprocessor.normalize(input_audio, config) -> NormalizedAudioResult`。
- 實作 ffmpeg adapter，輸出 `normalized.wav`。
- 驗證 duration、sample rate、channels 與輸出檔可讀性。
- 將 ffmpeg 錯誤轉成 pipeline domain error。
- 產生 preprocessing report，供 pipeline log 使用。

**不包含範圍**
- 不做 loudness normalization、降噪或 silence trimming。
- 不在 API request 中執行 ffmpeg。

**主要修改位置或建議目錄**
- ai_pipeline/preprocessing/
- ai_pipeline/contracts/audio_preprocessor.py
- tests/unit/preprocessing/
- tests/pipeline/

**輸入**
- original audio ArtifactRef 或 job-scoped temp path。
- preprocessing config。

**輸出**
- `normalized.wav` artifact。
- preprocessing metadata / report。

**API / Data Model / Storage 關聯**
- Data：`AudioFile.normalized_storage_key`、duration、sample_rate、channels。
- Storage：`jobs/{job_id}/audio/normalized.wav`。

**驗收標準**
- AudioPreprocessor 可被 mock。
- ffmpeg adapter 可處理短 MP3 / WAV。
- ffmpeg 失敗時不會進入 Demucs stage。

**測試要求**
- unit test：interface contract 與 error mapping。
- integration test：短 MP3 / WAV 轉 normalized WAV。
- error test：損壞音檔與 ffmpeg timeout。

**相依任務**
GS-P1-002, GS-P2-005

**風險與注意事項**
- adapter 可使用 local temp path，但跨模組傳遞必須回到 ArtifactRef 或 storage key。

### GS-P4-010 — 建立 MidiPostProcessor service 正式化

**Ticket ID**
GS-P4-010

**Ticket 名稱**
建立 MidiPostProcessor service 正式化

**背景與目的**
Phase 1 已有 MIDI 後處理初版；本 ticket 將其正式化為 pipeline stage，輸出使用者下載用 processed MIDI 與 notation 可消費的 `drum_events.json`。

**實作範圍**
- 定義 `MidiPostProcessor.process(raw_midi, audio_metadata, config) -> MidiPostProcessResult`。
- 正式化 General MIDI drum mapping、quantization、dedupe、velocity cleanup。
- 輸出 `processed_drum.mid` 與 `drum_events.json`。
- 產生 post-processing report：event_count、warnings、estimated_bpm。

**不包含範圍**
- 不做完整 tempo map。
- 不做 ghost note 精修或左右手 sticking 推論。
- 不提供使用者可調量化 UI。

**主要修改位置或建議目錄**
- ai_pipeline/midi/
- ai_pipeline/contracts/midi_post_processor.py
- tests/unit/midi/
- tests/pipeline/

**輸入**
- `raw_drum.mid` artifact。
- audio metadata。
- MIDI post-processing config。

**輸出**
- `processed_drum.mid`。
- `drum_events.json`。
- post-processing report。

**API / Data Model / Storage 關聯**
- Data：`DrumTrack.processed_midi_storage_key`、`drum_events_storage_key`、`event_count`、`estimated_bpm`、`warnings`。
- Storage：`jobs/{job_id}/midi/processed_drum.mid`、`jobs/{job_id}/events/drum_events.json`。

**驗收標準**
- raw MIDI 可轉成可 parse 的 processed MIDI。
- `drum_events.json` schema 穩定，可被 NotationGenerator 使用。
- 空或低事件數 MIDI 有明確 warning 或 failed 策略。

**測試要求**
- unit test：mapping、quantization、dedupe、velocity cleanup。
- integration test：raw MIDI → processed MIDI → drum_events JSON。

**相依任務**
GS-P1-005, GS-P2-005

**風險與注意事項**
- 量化策略要以可讀草稿為目標，不要在 MVP 追求專業扒譜級細節。

### GS-P4-011 — 建立 NotationGenerator / PdfExporter interface 與 worker integration

**Ticket ID**
GS-P4-011

**Ticket 名稱**
建立 NotationGenerator / PdfExporter interface 與 worker integration

**背景與目的**
Phase 1 已可產生 MusicXML / PDF 初版；本 ticket 將 notation 與 PDF export 正式化為可被 worker pipeline 呼叫的服務，並清楚處理 PDF 部分失敗。

**實作範圍**
- 定義 `NotationGenerator.generate(drum_events, metadata, config) -> MusicXmlResult`。
- 定義 `PdfExporter.export(musicxml, config) -> PdfExportResult`。
- 使用 `drum_events.json` 產生 percussion staff MusicXML。
- 以 MusicXML 為來源產生 PDF。
- PDF 失敗時建立 failed export metadata，不影響已成功的 MIDI / MusicXML。

**不包含範圍**
- 不做出版級 engraving。
- 不做線上譜面編輯。
- 不做音訊播放與譜面同步。

**主要修改位置或建議目錄**
- ai_pipeline/notation/
- ai_pipeline/contracts/notation_generator.py
- ai_pipeline/contracts/pdf_exporter.py
- worker/app/pipeline_runner.py
- tests/pipeline/

**輸入**
- `drum_events.json`。
- title、estimated BPM、time signature。
- PDF renderer config。

**輸出**
- `score.musicxml`。
- `score.pdf` 或 failed PDF export result。

**API / Data Model / Storage 關聯**
- Data：`ExportFile(type=musicxml|pdf)`。
- Storage：`jobs/{job_id}/notation/score.musicxml`、`jobs/{job_id}/exports/score.pdf`。

**驗收標準**
- MusicXML 可 parse 並可供前端預覽。
- PDF 成功時可下載；PDF 失敗時不阻斷 MIDI / MusicXML。
- NotationGenerator 與 PdfExporter 可被 mock。

**測試要求**
- unit test：drum event 到 notation mapping。
- integration test：drum_events JSON → MusicXML → PDF。
- error test：PDF renderer 失敗時 ExportFile failed。

**相依任務**
GS-P1-006, GS-P4-010, GS-P2-009

**風險與注意事項**
- MusicXML 是 MVP 譜面真相來源；前端不要從 MIDI 重新推導譜面。

## Phase 完成標準

- Worker 能呼叫正式 pipeline service。
- Demucs 與 ADTOF 透過 interface/adapter 接入。
- 每個 stage 寫入 artifact metadata。
- pipeline version 與模型版本被記錄。
